import reflex as rx

config = rx.Config(
    app_name="front",
    backend_port=8001,
    # 後端伺服器設在 8001，避免與 FastAPI 衝突（FastAPI 預設 8000）
    # 預設前端在 3000
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(),
    ],
)
