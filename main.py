import json
import os
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF

# === Namespaces ===
EX = Namespace("http://example.com/resource/")
HTTP = Namespace("http://www.w3.org/2011/http#")
BRICK = Namespace("https://brickschema.org/schema/Brick#")
REC = Namespace("https://w3id.org/rec#")

BASE_URL = "http://fiware.rwth-aachen.de/v2/entities/"

# === Load OpenAPI Spec Dynamically ===
def parse_openapi():
    with open("data/openAPI_spec.json") as f:
        spec = json.load(f)

    endpoints = []
    for path, methods in spec["paths"].items():
        for method, info in methods.items():
            entity_type = None
            headers = []
            for param in info.get("parameters", []):
                if param["name"] == "type":
                    entity_type = param["schema"].get("default")
                if param["in"] == "header":
                    headers.append({
                        "name": param["name"],
                        "default": param["schema"].get("default")
                    })
            if "/attrs/" in path:
                attribute = path.split("/attrs/")[1].split("/")[0]
                endpoints.append({
                    "method": method.upper(),
                    "path": path,
                    "entity_type": entity_type,
                    "attribute": attribute,
                    "headers": headers
                })
    return endpoints

# === Generate Headers as RDF Nodes ===
def create_header(g, header_name, header_value, suffix=""):
    header_uri = EX[f"Header_{header_name.replace('-', '')}{suffix}"]
    g.add((header_uri, RDF.type, HTTP.MessageHeader))
    g.add((header_uri, HTTP.fieldName, Literal(header_name)))
    g.add((header_uri, HTTP.fieldValue, Literal(header_value)))
    return header_uri

# === Main Generator ===
def main():
    g = Graph()
    g.parse("data/inpu_kg.ttl", format="turtle")
    g.parse("data/http4rdf_ontology.ttl", format="turtle")

    with open("data/original_data.json") as f:
        devices = json.load(f)

    endpoint_rules = parse_openapi()

    # Optional mapping from actual entity types to OpenAPI entity_type
    entity_type_alias = {
        "RadiatorThermostat": "Thermostat",
        "TemperatureSensor": "TemperatureSensor",
        "HotelRoom": None  # not used in OpenAPI
    }

    for dev in devices:
        dev_id = dev["id"]
        dev_type = dev["type"]
        safe_id = dev_id.replace(":", "_")

        # Match rule from OpenAPI
        mapped_type = entity_type_alias.get(dev_type)
        matched = next((ep for ep in endpoint_rules if ep["entity_type"] == mapped_type), None)

        if not matched:
            continue

        attr = matched["attribute"]
        method = matched["method"]
        full_uri = f"{BASE_URL}{dev_id}/attrs/{attr}/value"

        # === Create Brick Entity ===
        if dev_type == "TemperatureSensor":
            sensor_uri = EX[f"{dev_type}_{safe_id}"]
            g.add((sensor_uri, RDF.type, BRICK.Air_Temperature_Sensor))
            g.add((sensor_uri, RDF.value, URIRef(full_uri)))
            g.add((sensor_uri, BRICK.isPointOf, EX[f"HotelRoom_{safe_id}"]))

        elif dev_type == "RadiatorThermostat":
            thermo_uri = EX[f"{dev_type}_{safe_id}"]
            setpoint_uri = EX[f"temperatureSetpoint_{safe_id}"]
            g.add((thermo_uri, RDF.type, BRICK.Thermostat))
            g.add((thermo_uri, BRICK.hasLocation, EX[f"HotelRoom_{safe_id}"]))
            g.add((setpoint_uri, RDF.type, BRICK.Temperature_Setpoint))
            g.add((setpoint_uri, BRICK.isPointOf, thermo_uri))
            g.add((setpoint_uri, RDF.value, URIRef(full_uri)))

        elif dev_type == "HotelRoom":
            g.add((EX[f"HotelRoom_{safe_id}"], RDF.type, REC.Room))
            continue

        # === Create HTTP Request RDF ===
        request_uri = EX[f"{method}_{safe_id}"]
        g.add((request_uri, RDF.type, HTTP.Request))
        g.add((request_uri, HTTP.mthd, Literal(method)))
        g.add((request_uri, HTTP.requestURI, URIRef(full_uri)))

        # === Link All Headers from OpenAPI ===
        for header in matched["headers"]:
            header_node = create_header(
                g,
                header_name=header["name"],
                header_value=header["default"],
                suffix=f"_{safe_id}"
            )
            g.add((request_uri, HTTP.headers, header_node))

    # === Serialize Output ===
    os.makedirs("output", exist_ok=True)
    with open("output/final_output.ttl", "w") as f:
        f.write(g.serialize(format="turtle"))

    print("Done: RDF written to output/final_output.ttl")

if __name__ == "__main__":
    main()
