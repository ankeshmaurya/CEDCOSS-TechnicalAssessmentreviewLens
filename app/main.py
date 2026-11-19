from fastapi import FastAPI


app = FastAPI(title="ReviewLens")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
