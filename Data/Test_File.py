from rdflib import Graph, Namespace, Literal
from rdflib.namespace import RDF

# Use your function and constants
EX = Namespace("http://www.w3.org/2000/01/rdf-schema")  # <- corrected from rdfs
HTTP = Namespace("http://www.w3.org/2011/http#")

def create_header(g, header_name, header_value, suffix=""):
    header_uri = EX[f"Header_{header_name.replace('-', '')}{suffix}"]
    if (header_uri, None, None) not in g:
        g.add((header_uri, RDF.type, HTTP.MessageHeader))
        g.add((header_uri, HTTP.fieldName, Literal(header_name)))
        g.add((header_uri, HTTP.fieldValue, Literal(header_value)))
    return header_uri

# === TEST CODE ===
g = Graph()

uri = create_header(g, "Fiware-Service", "semantic_iot")
uri2 = create_header(g, "Content-Type", "application/json", "_Request")

# Print as Turtle
print(g.serialize(format="turtle"))
print("new")
