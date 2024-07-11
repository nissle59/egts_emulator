from fastapi import FastAPI, BackgroundTasks

import config
#import service
import service_threaded

app = FastAPI()

@app.get("/add")
def add_imei(imei: str, taskId: str, background_tasks: BackgroundTasks, regNumber:str = None, new_format=1):
    config.logger.info(f"Adding imei to queue, format: {new_format}")
    # if int(new_format) == 1:
    #     service_threaded.add_imei(imei=imei, route_id=taskId, sec_interval=config.sec_interval, new_format=1)
    # else:
    background_tasks.add_task(service_threaded.add_imei, imei, taskId, regNumber, config.sec_interval, 1)
    return {"status":"started", "id": int(str(imei)[-8:]), "imei": imei, "route": taskId}


@app.get("/get")
def get_data(imei: str):
    return service_threaded.get_imei(imei)


@app.get("/getAll")
def get_data_all():
    return service_threaded.get_imeis()


@app.get("/getList")
def get_data_list(imei: str):
    return service_threaded.get_imeis(imeis=imei)


@app.get("/stop")
def stop_imei(imei: str):
    return service_threaded.stop_imei(imei)

@app.get("/stopAll")
def stop_all():
    imeis = service_threaded.get_base_queues()
    res = []
    for imei in imeis:
        res.append(service_threaded.stop_imei(imei))
    return res