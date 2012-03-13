import urllib
import urllib2
import httplib
from graphUtils import GraphUtils
from progressCache import ProgressCache
import logging
import json
import time

class FriendsFinder(object):
    token = ''
    userID = ''
    numOfPairs = 100

    def __init__(self, token, userID = 'me', numOfPairs = 100):
        self.token = token
        self.userID = userID
        self.numOfPairs = numOfPairs

    def __callFacebookAPI(self, relativeUrl):
        url = 'https://graph.facebook.com/' + relativeUrl
        f = urllib2.urlopen(url)
        content = f.read()
        f.close()

        #content = content.replace('true', 'True').replace('false', 'False')
        return json.loads(content)

    def __postFacebookAPI(self, params, timeout):
        url = 'https://graph.facebook.com/'
        params = urllib.urlencode(params)
        f = urllib2.urlopen(url, params, timeout)
        content = f.read()
        f.close()

        return eval(content)

    def __getFriendsDict(self, id, wifeID):
        url = '%s/friends?access_token=%s' % (id, self.token)

        friends = self.__callFacebookAPI(url)
        friendsDict = {}
        for friend in friends['data']:
            if friend['id'] != wifeID:
                friendsDict[friend['id']] = friend['name']

        return friendsDict

    def __areFriends(self, id1, id2):
        url = '%s/friends/%s?access_token=%s' % (id1, id2, self.token)
        answer = self.__callFacebookAPI(url)

        return len(answer['data']) > 0

    def __getMutualFriends(self, friendID, friendName, friendIndex):
        url = '%s/mutualfriends/%s?access_token=%s' % (self.userID, friendID, self.token)
        mutualFriends = self.__callFacebookAPI(url)
        data = map(lambda x: x['id'], mutualFriends['data'])

        return {friendID: (friendIndex, friendName, data)}

    def __getBatchRequest(self, friends, wifeID):
        NUM_OF_ATTEMPTS = 5
        timeouts = range(60, 30 + 30 * (NUM_OF_ATTEMPTS + 1), 30)

        requests = json.dumps(map(lambda x: {'method': 'GET', 'relative_url': 'me/mutualfriends/%s' % x}, friends))
        mutualFriendsBatch = []
        for timeout in timeouts:
            try:
                mutualFriendsBatch = self.__postFacebookAPI({'access_token': self.token, 'batch': requests}, timeout)
                break
            except urllib2.HTTPError as e:
                logging.info('Error occurred - %s. Retrying...' % e.code)
#                print 'Error occurred - %s. Retrying...' % e.code
            except urllib2.URLError as e:
                logging.info('Error occurred - %s. Retrying...' % e.reason)
#                print 'Error occurred - %s. Retrying...' % e.reason
            except httplib.HTTPException, e:
                pass

        batches = []
        for idx, batch in enumerate(mutualFriendsBatch):
            body = json.loads(batch['body'])
            mutualFriends = map(lambda x: x['id'], body['data'])
            mutualFriends = filter(lambda x: x != wifeID and x != self.userID, mutualFriends)
            batches.append((friends[idx], mutualFriends))

        return batches

    def __getSignificantOtherID(self):
        url = '%s?access_token=%s' % (self.userID, self.token)
        profile = self.__callFacebookAPI(url)

        if 'significant_other' in profile:
            return profile['significant_other']['id']

        return 0


    def __getFriends(self, myFriends, wifeID):
        # separate the friend calls to batches of 50
        BATCH_SIZE = 50
        MUTUAL_FRIENDS_THRESHOLD = 1#len(myFriends) / 50
        idx = 0
        friendsList = []
        smallFriends = []
        numOfBatches = len(myFriends) / BATCH_SIZE + 1
        #numOfBatches = 1
        for batchIdx in range(numOfBatches):
            # insert progress into cache
            ProgressCache.set(self.userID, 'fetch_progress', float(batchIdx) / numOfBatches)

            start = batchIdx * BATCH_SIZE
            end = start + BATCH_SIZE
            friends = myFriends.keys()[start: end]
            logging.info('Getting batch %s to %s' % (start, end))
#            print 'Getting batch %s to %s' % (start, end)
            mutualBatch = self.__getBatchRequest(friends, wifeID)

            for mutual in mutualBatch:
                id, mutualFriends = mutual
                if len(mutualFriends) >= MUTUAL_FRIENDS_THRESHOLD:
                    friendsList.append((id, myFriends[id], idx, mutualFriends))
                    idx += 1
                else:
                    smallFriends.append(id)

        # set cache to done
        ProgressCache.set(self.userID, 'fetch_progress', 1.0)

        # remove friends with low mutual count from friends lists
        friendsList = map(lambda x: (x[0], x[1], x[2], list(set(x[3]).difference(smallFriends))), friendsList)
        return friendsList

    def getInterestingFriends(self):
        # get significant other ID
        significantOtherID = self.__getSignificantOtherID()
        logging.info('Significant Other ID: %s' % significantOtherID)

        # get all friends
        myFriends = self.__getFriendsDict(self.userID, significantOtherID)
        logging.info('Number of friends - %s' % len(myFriends))

        # create friends graph file
        friends = self.__getFriends(myFriends, significantOtherID)
        logging.info('Length of friends graph - %s' % len(friends))

        # read from file
#        f = open('friends.txt')
#        friends = eval(f.read())
#        f.close()

        # write to file
#        f = open('friends.txt', 'w')
#        f.write(str(friends))
#        f.close()

        graph = GraphUtils(self.userID, friends)
        friendLinks = graph.getFriends()
        return friendLinks[: self.numOfPairs]

#if __name__ == '__main__':
#    start = time.time()
#    finder = FriendsFinder('AAABlwUvZAB0EBAI6Cv8LYOsKfeUNJnV62x1e2gkdi8ICmBSzsbZA1FEsyz0DK1zqL5lQydPmQ3r8Un4ZBGEKKJnLHCZCfNS08Ca320ZCitRIf9ZAIZBcXXu')
#    friends = finder.getInterestingFriends()
#    print (time.time() - start) / 60
#    print friends