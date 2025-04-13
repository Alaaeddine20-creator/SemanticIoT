import json
import os
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF

# === Define Namespaces used in the RDF model ===
EX = Namespace("http://example.com/resource/")
HTTP = Namespace("http://www.w3.org/2011/http#")
BRICK = Namespace("https://brickschema.org/schema/Brick#")
REC = Namespace("https://w3id.org/rec#")

BASE_URL = "http://fiware.rwth-aachen.de/v2/entities/"

# === Parse OpenAPI Specification to extract request types, attributes, headers ===
def parse_openapi():
    with open("data/openAPI_spec.json") as f:
        spec = json.load(f)

    endpoints = []
    for path, methods in spec.get("paths", {}).items():
        for method_name, method_details in methods.items():
            entity_type = None
            headers = []
            # Collect parameters defined globally for the method
            parameters = method_details.get("parameters", [])
            for param in parameters:
                if param.get("name") == "type":
                    entity_type = param.get("schema", {}).get("default")
                if param.get("in") == "header":
                    headers.append({
                        "name": param.get("name"),
                        "default": param.get("schema", {}).get("default")
                    })

            # Try to detect the attribute dynamically from the path
            path_parts = path.strip("/").split("/")
            attribute = None
            if "attrs" in path_parts:
                try:
                    attr_index = path_parts.index("attrs") + 1
                    attribute = path_parts[attr_index]
                except IndexError:
                    continue  # Skip if path is malformed

            if attribute:
                endpoints.append({
                    "method": method_name.upper(),
                    "path": path,
                    "entity_type": entity_type,
                    "attribute": attribute,
                    "headers": headers
                })
    return endpoints

# === Dynamically create HTTP header nodes based on OpenAPI parameters ===
def create_header(g, header_name, header_value, suffix=""):
    header_uri = EX[f"Header_{header_name.replace('-', '')}{suffix.replace(':', '_')}"]
    # Check if header already exists before adding
    if (header_uri, None, None) not in g:
        g.add((header_uri, RDF.type, HTTP.MessageHeader))
        g.add((header_uri, HTTP.fieldName, Literal(header_name)))
        g.add((header_uri, HTTP.fieldValue, Literal(header_value)))
    return header_uri

# === Main function to generate RDF triples ===
def main():
    g = Graph()

    # Load pre-existing RDF data from input files
    g.parse("data/inpu_kg.ttl", format="turtle")
    g.parse("data/http4rdf_ontology.ttl", format="turtle")

    # Load device data (entity ID, type, etc.)
    with open("data/original_data.json") as f:
        devices = json.load(f)

    # Load OpenAPI specification and parse endpoint rules
    endpoint_rules = parse_openapi()

    # Map internal device types to OpenAPI entity types
    entity_type_alias = {
        "RadiatorThermostat": "Thermostat",
        "TemperatureSensor": "TemperatureSensor",
        "HotelRoom": "HotelRoom"
    }

    # Create a separate RDF graph for sorting and grouping
    data_graph = Graph()
    api_graph = Graph()
    header_graph = Graph()

    for dev in devices:
        dev_id = dev["id"]
        dev_type = dev["type"]
        safe_id = dev_id.replace(":", "_")  # clean version for RDF identifiers

        # Match OpenAPI endpoint for this device type
        mapped_type = entity_type_alias.get(dev_type)
        matched = next((ep for ep in endpoint_rules if ep["entity_type"] == mapped_type), None)

        if not matched:
            continue

        attr = matched["attribute"]
        method = matched["method"]
        full_uri = f"{BASE_URL}{dev_id}/attrs/{attr}/value"

        # === Create RDF Brick triples to describe the device ===
        instance_uri = EX[f"{dev_type}_{safe_id}"]
        location_uri = EX[f"HotelRoom_{safe_id}"]

        # General mapping for Brick classes based on keywords
        class_map = {
            "temperature": BRICK.Air_Temperature_Sensor,
            "co2": BRICK.CO2_Sensor,
            "humidity": BRICK.Humidity_Sensor,
            "occupancy": BRICK.Occupancy_Sensor,
            "thermostat": BRICK.Thermostat,
            "room": REC.Room
        }

        # Try to infer sensor class
        for keyword, brick_class in class_map.items():
            if keyword in dev_type.lower():
                if (instance_uri, RDF.type, brick_class) not in data_graph:
                    data_graph.add((instance_uri, RDF.type, brick_class))
                    if brick_class != REC.Room:
                        data_graph.add((instance_uri, RDF.value, URIRef(full_uri)))
                        if "Sensor" in str(brick_class):
                            data_graph.add((instance_uri, BRICK.isPointOf, location_uri))
                        elif brick_class == BRICK.Thermostat:
                            data_graph.add((instance_uri, BRICK.hasLocation, location_uri))
                            setpoint_uri = EX[f"temperatureSetpoint_{safe_id}"]
                            if (setpoint_uri, RDF.type, BRICK.Temperature_Setpoint) not in data_graph:
                                data_graph.add((setpoint_uri, RDF.type, BRICK.Temperature_Setpoint))
                                data_graph.add((setpoint_uri, BRICK.isPointOf, instance_uri))
                                data_graph.add((setpoint_uri, RDF.value, URIRef(full_uri)))
                break

        # === Create RDF triples to describe HTTP request dynamically ===
        request_uri = EX[f"{method}_{safe_id}"]
        if (request_uri, RDF.type, HTTP.Request) not in api_graph:
            api_graph.add((request_uri, RDF.type, HTTP.Request))
            api_graph.add((request_uri, HTTP.mthd, Literal(method)))
            api_graph.add((request_uri, HTTP.requestURI, URIRef(full_uri)))

        # === Add HTTP headers from OpenAPI to the request ===
        for header in matched["headers"]:
            header_node = create_header(
                header_graph,
                header_name=header["name"],
                header_value=header["default"],
                suffix=f"_{safe_id}"
            )
            api_graph.add((request_uri, HTTP.headers, header_node))

        # === Add query/path parameters as http:Parameter ===
        for param in matched.get("parameters", []):
            if param.get("in") in ["query", "path"]:
                param_name = param.get("name")
                param_value = param.get("schema", {}).get("default", "")
                param_uri = EX[f"Param_{param_name}_{safe_id}"]
                api_graph.add((param_uri, RDF.type, HTTP.Parameter))
                api_graph.add((param_uri, HTTP.paramName, Literal(param_name)))
                api_graph.add((param_uri, HTTP.paramValue, Literal(param_value)))
                api_graph.add((request_uri, HTTP.params, param_uri))

    # === Write final RDF graph to output file, organized ===
    os.makedirs("output", exist_ok=True)
    with open("output/final_output.ttl", "w") as f:
        f.write("""@prefix brick: <https://brickschema.org/schema/Brick#> .

#####  the existing workflow
""")
        f.write(data_graph.serialize(format="turtle"))
        f.write("""
#####  the API interaction
""")
        f.write(api_graph.serialize(format="turtle"))
        f.write("""
# Define common headers
""")
        f.write(header_graph.serialize(format="turtle"))

    print("Done: RDF written to output/final_output.ttl")

if __name__ == "__main__":
    main()
