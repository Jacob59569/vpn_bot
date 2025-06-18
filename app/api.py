from fastapi import FastAPI
from utils import add_client_to_config, generate_vless_link

app = FastAPI()

@app.post("/generate")
def generate():
    link = add_client_to_config()
    return link