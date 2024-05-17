import urllib.request
import json


class ApiService:
    token = '5jossnicxhn75lht7aimal7r2ocvg6o7'
    base_url = 'http://api-external.tm.8525.ru/rnis/'

    @classmethod
    def getRoute(cls, id):
        result = cls.send(f"emulation?token={cls.token}&taskId=" + str(id))
        return result

    @classmethod
    def getCoordinates(cls, id):
        result = cls.send("route/coordinates?routeId=" + str(id))
        return result

    @classmethod
    def getSegments(cls, id):
        result = cls.send("route/segments?routeId=" + str(id))
        return result

    @staticmethod
    def send(url):
        req = urllib.request.Request(ApiService.base_url + url)
        with urllib.request.urlopen(req) as response:
            body = response.read()
        return json.loads(body)
