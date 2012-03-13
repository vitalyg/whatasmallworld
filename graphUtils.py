import sys
from operator import itemgetter
from collections import namedtuple
import math
import logging
from progressCache import ProgressCache

class GraphUtils(object):
    """ Object depicting various social graph methods """
    userID = ''
    graph = {}
    names = {}
    keys = []
    path = []
    nextEdge = []

    def __init__(self, userID, friends):
        # create a dictionary for the graph and an index for the names
        self.userID = userID
        for line in friends:
            id, name, idx, friends = line
            self.graph[id] = (idx, friends)
            self.names[id] = name
            self.keys.append(id)

        self.__initGraph()
#        self.__calcFloydWarshall()

#        f = open('floyd.txt', 'w')
#        f.write(str(self.path) + '\n')
#        f.write(str(self.nextEdge))
#        f = open('floyd.txt')
#        self.path = eval(f.readline())
#        self.nextEdge = eval(f.readline())
#        f.close()


    def __initGraph(self):
        # initialize an array for Floyd-Warshall
        n = len(self.graph)
        self.path = [[sys.maxint] * n for i in range(n)]
        self.nextEdge = [[None] * n for i in range(n)]

        # init path
        for key, tuple in self.graph.items():
            idx, values = tuple
            self.path[idx][idx] = 0
            for value in values:
                self.path[idx][self.graph[value][0]] = 1

    # Floyd-Warshall
    def __calcFloydWarshall(self):
        n = len(self.graph)
        lastFloor = 0
        for k in range(n):
            # print algorithm progress
            floor = math.floor(float(k) / n * 10)
            if floor != lastFloor:
                logging.info('%s percent done' % (str(int(floor) * 10)))
#                print '%s percent done' % (str(int(floor) * 10))
                lastFloor = floor

            # cache algorithm progress
#            memcache.set('graph_progress', float(k) / n)
            ProgressCache.set(self.userID, 'graph_progress', float(k) / n)

            for i in range(n):
                if i == k:
                    continue

                for j in range(n):
                    if j == i or j == k:
                        continue

                    if self.path[i][k] + self.path[k][j] < self.path[i][j]:
                        self.path[i][j] = self.path[i][k] + self.path[k][j]
                        self.nextEdge[i][j] = [k]
                    elif 1 < self.path[i][k] + self.path[k][j] == self.path[i][j] < sys.maxint:
                        self.nextEdge[i][j].append(k)


        logging.info('100 percent done')
        ProgressCache.set(self.userID, 'graph_progress', 1.0)

    def __getName(self, index):
        return self.names[self.keys[index]]

    def __getAllPaths(self, i, j):
        if self.path[i][j] == sys.maxint:
            return []
        intermediates = self.nextEdge[i][j]
        if intermediates is None:
            return [[i, j]]
        else:
            paths = []
            for intermediate in intermediates:
                startPaths = self.__getAllPaths(i, intermediate)
                endPaths = self.__getAllPaths(intermediate, j)
                for startPath in startPaths:
                    for endPath in endPaths:
                        paths.append(startPath[: -1] + [intermediate] + endPath[1: ])
            return paths

    def __calcFriendsIntersection(self, edge):
        idx1, idx2 = edge
        friends1 = set(self.graph[self.keys[idx1]][1])
        friends2 = set(self.graph[self.keys[idx2]][1])
        intersection = friends1.intersection(friends2)

        if len(friends1) * len(friends2) > 0:
            return float(len(intersection) + 1) / min(len(friends1), len(friends2)), len(intersection), len(friends1), len(friends2)

        return 0, 0, 0, 0

    def __getMostVisitedEdges(self):
        edges = {}
        n = len(self.graph)
        for i in range(n):
#            memcache.set('edges_progress', float(i) / n)
            ProgressCache.set(self.userID, 'edges_progress', float(i) / n)
            for j in range(n):
                routes = self.__getAllPaths(i, j)
                for route in routes:
                    for k in range(len(route) - 1):
                        key = (route[k], route[k + 1])
                        if key[0] < key[1]:
                            if key not in edges:
                                edges[key] = 0.0
                            edges[key] += 1.0 / len(routes)

            ProgressCache.set(self.userID, 'edges_progress', 1.0)
#        f = open('edges.txt')
#        edges = eval(f.read())
#        f.close()

        for idx, key in enumerate(edges.keys()):
#            memcache.set('ratio_progress', float(idx) / len(edges))
            ProgressCache.set(self.userID, 'ratio_progress', float(idx) / len(edges))
            ratio = self.__calcFriendsIntersection(key)
            if ratio < 0.05:
                edges[key] = (edges[key], ratio)
            else:
                edges[key] = (1, ratio)
            ProgressCache.set(self.userID, 'ratio_progress', 1.0)
        return edges

    def __getFriendsByIntersection(self):
        edges = {}
        n = len(self.graph)
        for i in range(n):
            ProgressCache.set(self.userID, 'graph_progress', float(i) / n)
            for j in range(i + 1, n):
                key = i, j
                if self.path[i][j] < sys.maxint:
                    edges[key] = self.__calcFriendsIntersection(key)
                else:
#                    edges[key] = sys.maxint
                    edges[key] = sys.maxint, sys.maxint, sys.maxint, sys.maxint
        ProgressCache.set(self.userID, 'graph_progress', 1.0)
        return edges


    def getFriends(self):
        Couple = namedtuple('Couple', 'firstName firstID secondName secondID')
        edges = self.__getFriendsByIntersection()
        sortedEdges = sorted(edges.iteritems(), key = itemgetter(1))
        namedEdges = map(lambda x: Couple(self.__getName(x[0][0]), self.keys[x[0][0]], self.__getName(x[0][1]), self.keys[x[0][1]]), sortedEdges)
#        sortedEdges = sorted(edges.iteritems(), key = lambda x: x[1][0])
#        namedEdges = map(lambda x: (self.__getName(x[0][0]), self.keys[x[0][0]], self.__getName(x[0][1]), self.keys[x[0][1]], x[1][0], x[1][1], x[1][2], x[1][3]), sortedEdges)

        return namedEdges
