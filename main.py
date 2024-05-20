from fastapi import FastAPI, BackgroundTasks
import service

app = FastAPI()

@app.get("/add")
def add_imei(imei: str, taskId: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(service.add_imei, imei, taskId)
    return {"id": int(str(imei)[-8:]),"imei": imei, "route": taskId}