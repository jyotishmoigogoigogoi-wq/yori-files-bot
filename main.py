import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from config import settings
from db import init_db
from bot import dp, bot
from api import router as api_router
import logging

logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    asyncio.create_task(dp.start_polling(bot))
    yield
    # Shutdown
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(api_router)

@app.get("/")
async def root():
    return FileResponse("templates/index.html")

@app.get("/share/{token}")
async def share_view(token: str):
    return FileResponse("templates/index.html") # Handled via JS client-side routing
