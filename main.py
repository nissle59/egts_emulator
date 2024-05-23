from fastapi import FastAPI, BackgroundTasks
#import service
import service_threaded

app = FastAPI()

@app.get("/add")
def add_imei(imei: str, taskId: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(service_threaded.add_imei, imei, taskId)
    return {"status":"started", "id": int(str(imei)[-8:]), "imei": imei, "route": taskId}


@app.get("/get")
def get_data(imei: str):
    return service_threaded.get_imei_point(imei)


@app.get("/stop")
def stop_imei(imei: str):
    return service_threaded.stop_imei(imei)