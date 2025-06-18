from fastapi import FastAPI
from utils import add_client_to_config

app = FastAPI()

@app.post("/generate")
def generate():
    link = add_client_to_config()
    return link