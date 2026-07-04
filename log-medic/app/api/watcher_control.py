from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/watcher")


@router.post("/pause")
def pause_watcher(request: Request):
    request.app.state.watcher_manager.pause()
    return {"paused": True}


@router.post("/resume")
def resume_watcher(request: Request):
    request.app.state.watcher_manager.resume()
    return {"paused": False}
