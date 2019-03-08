from rdflib.plugins.stores.sparqlstore import SPARQLStore
from source_context import SourceContext
from rdflib import URIRef, Literal
from rdflib.namespace import Namespace, RDF, SKOS, split_uri
from collections import namedtuple, Counter
import pickle
from setting import endpoint, wikidata_endpoint

sparql = SPARQLStore(endpoint)
wikidata_sparql = SPARQLStore(wikidata_endpoint)
AIDA = Namespace('https://tac.nist.gov/tracks/SM-KBP/2018/ontologies/InterchangeOntology#')
WDT = Namespace('http://www.wikidata.org/prop/direct/')
namespaces = {
    'aida': AIDA,
    'rdf': RDF,
    'skos': SKOS,
    'wdt': WDT
}
try:
  pickled = pickle.load(open('cluster.pkl', 'rb'))
except FileNotFoundError:
    pickled = {}
types = namedtuple('AIDATypes', ['Entity', 'Events'])(AIDA.Entity, AIDA.Event)


def get_cluster(uri):
    if Cluster.ask(uri):
        return Cluster(uri)
    return None


def recover_doc_online(doc_id):
    import json
    query_label_location = """
    SELECT DISTINCT ?label ?start ?end ?justificationType WHERE {
        ?justification a aida:TextJustification ;
                       skos:prefLabel ?label ;
                       aida:source ?source ;
                       aida:startOffset ?start ;
                       aida:endOffsetInclusive ?end ;
                       aida:privateData ?privateData .
        ?privateData aida:system <http://www.rpi.edu> ; aida:jsonContent ?justificationType
    }
    ORDER BY ?start
    """
    doc_recover = ''
    lend = 0
    for label, start, end, j in sparql.query(query_label_location, namespaces, {'source': Literal(doc_id)}):
        doc_recover += ' ' * (int(start)-lend)
        if json.loads(j).get('justificationType') == 'pronominal_mention':
            doc_recover += '<span style="color: red"><b>' + label + '</b></span>'
        else:
            doc_recover += '<u>' + label + '</u>'
        lend = int(end)
    return doc_recover


class Cluster:
    def __init__(self, uri):
        self.uri = URIRef(uri)
        self.__prototype = None
        self.__type = None
        self.__members = []
        self.__forward = None
        self.__backward = None
        self.__targets = Counter()
        self.__qnodesURL = {}
        self.__qnodesLabel = {}
        self.__qnodesAliases = {}

    @property
    def href(self):
        return self.uri.replace('http://www.isi.edu/gaia', '/cluster').replace('http://www.columbia.edu', '/cluster')

    @property
    def label(self):
        if self.uri in pickled and 'label' in pickled[self.uri]:
            return pickled[self.uri]['label']
        return self.prototype.label

    @property
    def prototype(self):
        if not self.__prototype:
            self._init_cluster_prototype()
        return self.__prototype

    @property
    def type(self):
        if self.uri in pickled and 'type' in pickled[self.uri]:
            return pickled[self.uri]['type']
        if not self.__type:
            self._init_cluster_prototype()
        return self.__type

    @property
    def members(self):
        if not self.__members:
            self._init_cluster_members()
        return self.__members

    @property
    def targets(self):
        if not self.__targets:
            self._init_cluster_members()
        return self.__targets.most_common()

    @property
    def targetsSize(self):
        return len(self.targets)

    @property
    def qnodesURL(self):
        if not self.__qnodesURL:
            self._init_cluster_members()
        return self.__qnodesURL

    @property
    def size(self):
        if self.__members:
            return len(self.__members)
        return self._query_for_size()

    @property
    def forward(self):
        if self.__forward is None:
            self.__forward = set()
            self._init_forward_clusters()
        return self.__forward

    @property
    def backward(self):
        if self.__backward is None:
            self.__backward = set()
            self._init_backward_clusters()
        return self.__backward

    @property
    def neighbors(self):
        return self.forward | self.backward

    def neighborhood(self, hop=1):
        if hop == 1 and self.prototype.type != AIDA.Relation:
            hood = self.neighbors
            # for neighbor in [x for x in self.neighbors if x.subject.proto]
            for neighbor in self.neighbors:
                if neighbor.subject.prototype.type == AIDA.Relation:
                    hood |= neighbor.subject.neighbors
            return hood
        if hop <= 1:
            return self.neighbors
        hood = set()
        for neighbor in self.neighbors:
            hood |= neighbor.subject.neighborhood(hop-1)
            hood |= neighbor.object.neighborhood(hop-1)
        return hood

    @property
    def img(self):
        import os.path
        _, name = split_uri(self.uri)
        svgpath = 'static/img/' + name + '.svg'
        if os.path.isfile(svgpath):
            return name

        from graph import SuperEdgeBasedGraph
        graph = SuperEdgeBasedGraph(self.neighborhood(), self, self.uri)
        path = graph.dot()
        return graph.name

    @classmethod
    def ask(cls, uri):
        query = "ASK { ?cluster a aida:SameAsCluster }"
        for ans in sparql.query(query, namespaces, {'cluster': URIRef(uri)}):
            return ans
        return False

    def _init_cluster_prototype(self):
        query = """
SELECT ?prototype (MIN(?label) AS ?mlabel) ?type ?category
WHERE {
    ?cluster aida:prototype ?prototype .
    ?prototype a ?type .
    OPTIONAL { ?prototype aida:hasName ?label } .
    ?statement a rdf:Statement ;
               rdf:subject ?prototype ;
               rdf:predicate rdf:type ;
               rdf:object ?category ;
}
GROUP BY ?prototype ?type ?category """
        for prototype, label, type_, cate in sparql.query(query, namespaces, {'cluster': self.uri}):
            if not label:
                _, label = split_uri(cate)
            self.__prototype = ClusterMember(prototype, label, type_)
            self.__type = cate

    def _init_cluster_members(self):
        query = """
SELECT ?member (MIN(?label) AS ?mlabel) ?type ?target
WHERE {
  ?membership aida:cluster ?cluster ;
              aida:clusterMember ?member .
  OPTIONAL { ?member aida:hasName ?label } .
  OPTIONAL { ?member aida:link/aida:linkTarget ?target } .
  ?statement a rdf:Statement ;
             rdf:subject ?member ;
             rdf:predicate rdf:type ;
             rdf:object ?type .
}
GROUP BY ?member ?type ?target """
        for member, label, type_, target in sparql.query(query, namespaces, {'cluster': self.uri}):
            if target:
                target = str(target)
                target = target[target.find(':')+1:]
                if "NIL" not in target:
                    target = '/' + target.replace('.', '/')
                self.__targets[target] += 1
            self.__members.append(ClusterMember(member, label, type_, target))

        for member in self.__members:
            target = member.target
            if 'NIL' not in target:
                if target not in self.__qnodesURL:
                    self.__qnodesURL[target] = member.qURL
                    self.__qnodesLabel[target] = member.qLabel
                    self.__qnodesAliases[target] = member.qAliases
                else:
                    # trying to reduce number of queries
                    member.set_qnode_url(self.__qnodesURL[target])
                    member.set_qnode_label(self.__qnodesLabel[target])
                    member.set_qnode_aliases(self.__qnodesAliases[target])

    def _init_forward_clusters(self):
        query = """
SELECT ?p ?o ?cnt
WHERE {
  ?s aida:prototype ?proto1 .
  ?o aida:prototype ?proto2 .
  ?se rdf:subject ?proto1 ;
      rdf:predicate ?p ;
      rdf:object ?proto2 ;
      aida:confidence/aida:confidenceValue ?conf .
  BIND(ROUND(1/(2*(1-?conf))) as ?cnt)
} """
        for p, o, cnt in sparql.query(query, namespaces, {'s': self.uri}):
            self.__forward.add(SuperEdge(self, Cluster(o), p, int(cnt)))

    def _init_backward_clusters(self):
        query = """
SELECT ?s ?p ?cnt
WHERE {
  ?s aida:prototype ?proto1 .
  ?o aida:prototype ?proto2 .
  ?se rdf:subject ?proto1 ;
      rdf:predicate ?p ;
      rdf:object ?proto2 ;
      aida:confidence/aida:confidenceValue ?conf .
  BIND(ROUND(1/(2*(1-?conf))) as ?cnt)
} """
        for s, p, cnt in sparql.query(query, namespaces, {'o': self.uri}):
            self.__backward.add(SuperEdge(Cluster(s), self, p, int(cnt)))

    def _query_for_size(self):
        if self.uri in pickled and 'size' in pickled[self.uri]:
            return pickled[self.uri]['size']
        query = """
SELECT (COUNT(?member) AS ?size)
WHERE {
    ?membership aida:cluster ?cluster ;
                aida:clusterMember ?member .
}  """
        for size, in sparql.query(query, namespaces, {'cluster': self.uri}):
            return int(size)
        return 0

    def __hash__(self):
        return self.uri.__hash__()

    def __eq__(self, other):
        return isinstance(other, Cluster) and str(self.uri) == str(other.uri)


class SuperEdge:
    def __init__(self, s: Cluster, o: Cluster, p: URIRef, n: int):
        self.subject = s
        self.predicate = p
        self.object = o
        self.count = n

    def __hash__(self):
        return hash((self.subject.uri, self.predicate, self.object.uri))

    def __eq__(self, other):
        return isinstance(other, SuperEdge) and str(self.subject.uri) == str(other.subject.uri) and str(
            self.predicate) == str(other.predicate) and str(self.object.uri) == str(other.object.uri)


class ClusterMember:
    def __init__(self, uri, label=None, type_=None, target=None):
        self.uri = URIRef(uri)
        self.__label = label
        self.__all_labels = None
        self.__type = type_
        self.__target = target
        self.__qLabel = None
        self.__qAliases = None
        self.__qURL = None
        self.__source = None
        self.__context_pos = []
        self.__context_extractor = None
        self.__cluster: Cluster = None

    @property
    def label(self):
        if not self.__label:
            self._init_member()
        return self.__label

    @property
    def all_labels(self):
        if not self.__all_labels:
            self.__all_labels = ""
            query = """
                SELECT ?label (COUNT(?label) AS ?n)
                WHERE {
                  ?member aida:justifiedBy/skos:prefLabel ?label .
                }
                GROUP BY ?label
                ORDER BY DESC(?n)
            """
            labels = []
            for label, n in sparql.query(query, namespaces, {'member': self.uri}):
                labels.append('{}(x{})'.format(label, n))
            self.__all_labels = ", ".join(labels)

        return self.__all_labels

    @property
    def type(self):
        if not self.__type:
            self._init_member()
        return self.__type

    @property
    def type_text(self):
        _, text = split_uri(self.type)
        return text

    @property
    def target(self):
        if self.__target is None:
            self._init_member()
        return self.__target

    @property
    def qURL(self):
        if self.__qURL is None and self.target:
            self._init_qNode()
        return self.__qURL

    def set_qnode_url(self, url):
        self.__qURL = url

    @property
    def qLabel(self):
        if self.__qLabel is None and self.target:
            self._init_qNode()
        return self.__qLabel

    def set_qnode_label(self, label):
        self.__qLabel = label

    @property
    def qAliases(self):
        if self.__qAliases is None and self.target:
            self._init_qNode()
        return self.__qAliases

    def set_qnode_aliases(self, aliases):
        self.__qAliases = aliases

    def _init_qNode(self):
        self.__qURL = False
        self.__qLabel = False
        self.__qAliases = False

        if self.target and "NIL" not in self.target:
            query = """
                SELECT ?qid ?label ?alias WHERE {
                  ?qid wdt:P646 ?freebase .
                  ?qid rdfs:label ?label filter (lang(?label) = "en") .
                  ?qid skos:altLabel ?alias filter (lang(?alias) = "en") .
                }
            """
            aliases = []
            for qid, label, alias in wikidata_sparql.query(query, namespaces, {'freebase': Literal(self.target)}):
                if not self.__qURL:
                    self.__qURL = str(qid)
                if not self.__qLabel:
                    self.__qLabel = label
                aliases.append(str(alias))
            self.__qAliases = ', '.join(aliases)

    @property
    def context_extractor(self):
        if self.__context_extractor is None:
            self.__context_extractor = SourceContext(self.source)
        return self.__context_extractor

    @property
    def roles(self):
        query = """
        SELECT ?pred ?obj ?objtype (MIN(?objlbl) AS ?objlabel)
        WHERE {
            ?statement rdf:subject ?event ;
                       rdf:predicate ?pred ;
                       rdf:object ?obj .
            ?objstate rdf:subject ?obj ;
                      rdf:predicate rdf:type ;
                      rdf:object ?objtype .
            OPTIONAL { ?obj aida:hasName ?objlbl }
        }
        GROUP BY ?pred ?obj ?objtype
        """
        for pred, obj, obj_type, obj_lbl in sparql.query(query, namespaces, {'event': self.uri}):
            if not obj_lbl:
                _, obj_lbl = split_uri(obj_type)
            # _, pred = split_uri(pred)
            ind = pred.find('_')
            pred = pred[ind+1:]
            yield pred, ClusterMember(obj, obj_lbl, obj_type)

    @property
    def events_by_role(self):
      query = """
      SELECT ?pred ?event ?event_type (MIN(?lbl) AS ?label)
      WHERE {
          ?event a aida:Event .
          ?statement rdf:subject ?event ;
                    rdf:predicate ?pred ;
                    rdf:object ?obj .
          ?event_state rdf:subject ?event ;
                    rdf:predicate rdf:type ;
                    rdf:object ?event_type .
          OPTIONAL { ?event aida:justifiedBy/skos:prefLabel ?lbl }
      }
      GROUP BY ?pred ?event ?event_type
      """
      for pred, event, event_type, event_lbl in sparql.query(query, namespaces, {'obj': self.uri}):
          if not event_lbl:
              _, event_lbl = split_uri(event_type)
          ind = pred.find('_')
          pred = pred[ind+1:]
          yield pred, ClusterMember(event, event_lbl, event_type)

    @property
    def cluster(self):
        if self.__cluster is None:
            query = "SELECT ?cluster WHERE { ?membership aida:cluster ?cluster ; aida:clusterMember ?member . }"
            for cluster, in sparql.query(query, namespaces, {'member': self.uri}):
                self.__cluster = get_cluster(cluster)
        return self.__cluster

    def _init_member(self):
        query = """
SELECT ?label ?type ?target
WHERE {
  OPTIONAL { ?member aida:hasName ?label }
  OPTIONAL { ?member aida:justifiedBy ?justification .
    ?justification skos:prefLabel ?label }
  OPTIONAL { ?obj aida:link/aida:linkTarget ?target }
  ?statement rdf:subject ?member ;
             rdf:predicate rdf:type ;
             rdf:object ?type .
}
LIMIT 1 """
        for label, type_, target in sparql.query(query, namespaces, {'member': self.uri}):
            if not label:
                _, label = split_uri(type_)
            self.__label = label
            self.__type = type_
            if target:
                target = target[target.find(':')+1:]
                if "NIL" not in target:
                    target = '/' + target.replace('.', '/')
                self.__target = target
            else:
                target = False

    def _init_source(self):
        query = """
SELECT DISTINCT ?source ?start ?end
WHERE {
  ?member aida:justifiedBy ?justification .
  ?justification aida:source ?source ;
                 aida:startOffset ?start ;
                 aida:endOffsetInclusive ?end .
}
ORDER BY ?start """
        for source, start, end in sparql.query(query, namespaces, {'member': self.uri}):
            self.__source = str(source)
            self.__context_pos.append((int(start), int(end)))

    @property
    def source(self):
        if not self.__source:
            self._init_source()
        return self.__source

    @property
    def mention(self):
        if self.context_extractor.doc_exists():
            for start, end in self.__context_pos:
                res = self.context_extractor.query_context(start, end)
                if not res:
                    continue
                yield res

    def __hash__(self):
        return self.uri.__hash__()


ClusterSummary = namedtuple('ClusterSummary', ['uri', 'href', 'label', 'count'])


def get_cluster_list(type_=None, limit=10, offset=0, sortby='size'):
    query = """
SELECT ?cluster ?label (COUNT(?member) AS ?memberN)
WHERE {
    ?cluster aida:prototype ?prototype .
    ?prototype a ?type .
    label_string
    ?membership aida:cluster ?cluster ;
              aida:clusterMember ?member .
}
GROUP BY ?cluster ?label
ORDER BY order_by
"""
    if type_ == AIDA.Entity:
        query = query.replace('?type', type_.n3())
        query = query.replace('label_string', '?prototype aida:hasName ?label .')
        query = query.replace('order_by', 'DESC(?memberN)')
    if type_ == AIDA.Event:
        query = query.replace('?type', type_.n3())
        query = query.replace('label_string', '?s rdf:subject ?prototype ; rdf:predicate rdf:type ; rdf:object ?label .')
        if sortby == 'type':
            query = query.replace('order_by', '?label DESC(?memberN)')
        else:
            query = query.replace('order_by', 'DESC(?memberN) ?label')
    if limit:
        query += " LIMIT " + str(limit)
    if offset:
        query += " OFFSET " + str(offset)
    for u, l, c in sparql.query(query, namespaces):
        if isinstance(l, URIRef):
            _, l = split_uri(l)
        yield ClusterSummary(u, u.replace('http://www.isi.edu/gaia', '/cluster').replace(
          'http://www.columbia.edu', '/cluster'), l, c)


if __name__ == '__main__':
    # cluster = get_cluster('http://www.isi.edu/gaia/entities/2dd85bb7-fea9-44ab-b3b8-d2272d874a25-cluster')
    cluster = get_cluster('http://www.isi.edu/gaia/entities/5c5da320-3a64-4144-9c03-d6533b898050-cluster')
    print(cluster.label, cluster.uri, cluster.type, cluster.prototype.type)
    print(cluster.size)
    for member in cluster.members:
        print(member.label, member.type, member.source, member.uri)
