from fastapi import FastAPI, BackgroundTasks
import service

app = FastAPI()

@app.get("/add")
def add_imei(imei: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(service.add_imei, imei)
    return {"imei": imei}