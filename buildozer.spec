[app]
title = EDITH
package.name = edith
package.domain = com.swarit.edith
source.dir = app
source.include_exts = py,png,jpg,html,json,txt,env,ico
source.include_patterns = assets/*,assets/**/*
version = 2.0

requirements = python3,
    kivy==2.3.0,
    pillow,
    fastapi==0.111.0,
    uvicorn==0.29.0,
    anyio==4.3.0,
    httpx==0.27.0,
    python-dotenv==1.0.1,
    aiohttp,
    authlib==1.3.1,
    itsdangerous==2.2.0,
    python-multipart==0.0.9,
    pydantic==2.7.1,
    pydantic-core==2.18.2,
    starlette==0.37.2,
    sniffio,
    h11,
    click,
    certifi,
    charset-normalizer,
    idna,
    urllib3,
    typing-extensions,
    annotated-types,
    edge-tts,
    websockets

android.minapi = 26
android.api = 33
android.ndk = 25b
android.ndk_api = 21
android.accept_sdk_license = True
android.archs = arm64-v8a

android.permissions = INTERNET,
    RECORD_AUDIO,
    MODIFY_AUDIO_SETTINGS,
    READ_EXTERNAL_STORAGE,
    WRITE_EXTERNAL_STORAGE,
    FOREGROUND_SERVICE,
    WAKE_LOCK

android.features = android.hardware.microphone
android.foreground_service = True

icon.filename = %(source.dir)s/assets/edith_icon.png
presplash.filename = %(source.dir)s/assets/splash.png
presplash_color = #0a0a12

orientation = portrait
fullscreen = 0

p4a.bootstrap = sdl2
p4a.branch = develop

[buildozer]
log_level = 2
warn_on_root = 1
