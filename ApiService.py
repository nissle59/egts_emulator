import urllib.request
import json


class ApiService:
    base_url = 'http://transpropusk.crm.8525.ru/api/services/rnis/'

    @classmethod
    def getRoute(cls, id):
        result = cls.send("route?routeId=" + str(id))
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
        return json.loads(body)['results']
