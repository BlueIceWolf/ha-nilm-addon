# HA NILM Add-on Repository

Dieses Repository enthält einen Home Assistant Add-on namens **HA NILM Detector**. Der eigentliche Add-on-Code befindet sich im Unterordner `ha-nilm-detector/`.

## Struktur

```
ha-nilm-addon/           # Repository-Wurzel
├── repository.yaml       # HA Add-on Repository Definition
├── ha-nilm-detector/    # Add-on selbst
│   ├── config.yaml
│   ├── Dockerfile
│   ├── README.md        # Ausführliche Add-on-Dokumentation
│   └── ...
└── tests/               # Entwicklungs- und Testdateien
```

Wenn du das Add-on in Home Assistant installieren möchtest, verwende einfach die Repository-URL:

```
https://github.com/BlueIceWolf/ha-nilm-addon
```

Mehr Informationen findest du im `ha-nilm-detector/README.md`.