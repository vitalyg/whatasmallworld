from google.appengine.api import memcache

class ProgressCache(object):

    @staticmethod
    def __getKey(userID, prop):
        return '%s__%s' % (userID, prop)

    @staticmethod
    def set(userID, prop, value):
#        return
        memcache.set(ProgressCache.__getKey(userID, prop), value)

    @staticmethod
    def get(userID, prop):
        return memcache.get(ProgressCache.__getKey(userID, prop))

    @staticmethod
    def getMulti(userID, props):
        keys = []
        for prop in props:
            keys.append(ProgressCache.__getKey(userID, prop))
        return memcache.get_multi(keys)

    @staticmethod
    def setMulti(userID, dict):
        newDict = {}
        for key, value in dict.items():
            newDict[ProgressCache.__getKey(userID, key)] = value

        memcache.set_multi(newDict)

    @staticmethod
    def flush():
        memcache.flush_all()

