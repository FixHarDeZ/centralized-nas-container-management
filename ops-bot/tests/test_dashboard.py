import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.db import get_db, close_db


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH', str(tmp_path / 'dashboard.db'))


HEADERS = {'Origin': 'http://test', 'X-Ops-Settings': '1'}


@pytest.mark.asyncio
async def test_settings_persist_reset_and_reject_invalid_writes():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/dashboard/settings', json={'model': 'mimo-test'}, headers=HEADERS)
        assert response.status_code == 200
        await close_db()
        page = await client.get('/dashboard/settings')
        assert 'mimo-test' in page.text
        bad = await client.post('/dashboard/settings', json={'model': '<script>bad</script>'}, headers=HEADERS)
        assert bad.status_code == 422
        assert (await client.post('/dashboard/settings', json={'model': 'bad'})).status_code == 403
        assert (await client.post('/dashboard/settings', json={'model': 'bad'}, headers={**HEADERS, 'Origin': 'https://evil.test'})).status_code == 403
        reset = await client.post('/dashboard/settings', json={'model': None}, headers=HEADERS)
        assert reset.status_code == 200
        assert reset.json()['model'] == 'mimo-v2.5-pro'
        assert reset.json()['source'] == 'environment'


@pytest.mark.asyncio
async def test_history_filters_pagination_and_escaped_content():
    db = await get_db()
    for number in range(26):
        cursor = await db.execute('INSERT INTO incidents (service_name, status) VALUES (?, ?)', (f'worker-{number:02}', 'down'))
        await db.execute('INSERT INTO analyses (incident_id, severity, root_cause) VALUES (?, ?, ?)', (cursor.lastrowid, 'critical' if number == 0 else 'info', '<script>alert(1)</script>'))
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        page = await client.get('/dashboard?q=worker-00&severity=critical')
        assert page.status_code == 200
        assert 'worker-00' in page.text
        assert 'worker-01' not in page.text
        assert '<script>alert(1)</script>' not in page.text
        assert '&lt;script&gt;' in page.text
        page2 = await client.get('/dashboard?page=2')
        assert 'worker-00' in page2.text
        assert 'worker-25' not in page2.text
        assert (await client.get('/dashboard/incident/999')).status_code == 404


@pytest.mark.asyncio
async def test_legacy_and_corrupt_reports_render_safely():
    db = await get_db()
    await db.execute("INSERT INTO incidents (id, service_name, status) VALUES (1, 'legacy', 'down')")
    await db.execute("INSERT INTO analyses (incident_id, root_cause, severity, report_json, fix_commands) VALUES (1, 'old cause', 'warning', 'broken{', 'broken[')")
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/dashboard/incident/1')
        assert response.status_code == 200
        assert 'old cause' in response.text


@pytest.mark.asyncio
async def test_model_discovery_sanitizes_failure_and_lists_provider_ids(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch
    monkeypatch.setenv('MIMO_API_KEY', 'test-only-key')
    provider = AsyncMock()
    provider.models.list.return_value = MagicMock(data=[MagicMock(id='mimo-z'), MagicMock(id='mimo-a'), MagicMock(id='mimo-z'), MagicMock(id='<bad>')])
    with patch('app.dashboard.AsyncOpenAI') as factory:
        factory.return_value.__aenter__.return_value = provider
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            result = await client.get('/dashboard/api/models')
            assert result.status_code == 200
            assert result.json()['models'] == ['mimo-a', 'mimo-z']
            provider.models.list.side_effect = RuntimeError('secret-provider-details')
            result = await client.get('/dashboard/api/models')
            assert result.status_code == 502
            assert 'secret-provider-details' not in result.text


@pytest.mark.asyncio
async def test_settings_validation_never_changes_saved_model():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        await client.post('/dashboard/settings', json={'model': 'mimo-saved'}, headers=HEADERS)
        for payload in ({}, {'model': ''}, {'model': 'x' * 129}, {'model': 'with space'}, {'model': 123}, {'model': 'valid', 'api_key': 'no'}):
            result = await client.post('/dashboard/settings', json=payload, headers=HEADERS)
            assert result.status_code == 422
        assert 'mimo-saved' in (await client.get('/dashboard/settings')).text


@pytest.mark.asyncio
async def test_latest_report_and_query_bounds():
    db = await get_db()
    await db.execute("INSERT INTO incidents (id, service_name, status) VALUES (1, 'unique-service', 'down')")
    await db.execute("INSERT INTO analyses (incident_id, root_cause, severity) VALUES (1, 'old', 'critical')")
    await db.execute("INSERT INTO analyses (incident_id, root_cause, severity) VALUES (1, 'new-result', 'info')")
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        page = await client.get('/dashboard?severity=critical')
        assert 'unique-service' not in page.text
        page = await client.get('/dashboard?page=999')
        assert page.text.count('class="service-link"') == 1
        assert 'new-result' in page.text
        for path in ('/dashboard?page=0', '/dashboard?severity=unknown'):
            assert (await client.get(path)).status_code == 422
