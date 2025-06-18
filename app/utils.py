import uuid
import json
import subprocess
from pathlib import Path

XRAY_CONFIG_PATH = Path("/app/xray/config.json")
DOMAIN = "shieldvpn.ru"
PORT = 443
SERVICENAME = "vless-grpc"

def add_client_to_config():
    with open(XRAY_CONFIG_PATH) as f:
        conf = json.load(f)

    uid = str(uuid.uuid4())
    email = f"user@{DOMAIN}"

    client = {"id": uid, "email": email}
    conf["inbounds"][0]["settings"]["clients"].append(client)

    with open(XRAY_CONFIG_PATH, "w") as f:
        json.dump(conf, f, indent=2)

    subprocess.run(["docker", "kill", "-s", "SIGHUP", "vpn_xray"])  # перезагрузить XRAY конфиг без рестарта
    return generate_vless_link(uid, email)

def generate_vless_link(uid, email):
    return f"vless://{uid}@{DOMAIN}:{PORT}?encryption=none&security=tls&type=grpc&serviceName={SERVICENAME}#{email}"