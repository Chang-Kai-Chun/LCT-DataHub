"""Reflex 設定。

Port（2026-11-06 決定）：FastAPI 8000、Reflex 後端 8001、前端 3000，三者不可重複。
"""
import reflex as rx

config = rx.Config(
    app_name="front",
    frontend_port=3000,
    backend_port=8001,
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(theme=rx.theme(accent_color="blue", radius="medium")),
    ],
)
