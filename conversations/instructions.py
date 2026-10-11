"""Catálogo local: ilustraciones propias y referencias suministradas para demo."""

from pathlib import Path
import logging

from django.urls import reverse

ASSET_ROOT = Path(__file__).resolve().parent / "instruction_assets"
PHOTO_ASSETS = {
    "poe": "poe_locate_demo.jpg",
    "lights": "poe_power_indicator_demo.jpg",
    "ethernet": "ethernet_inspection_demo.jpg",
}
GUIDE_TOPICS = {'cpe-offline': ('poe','lights','ethernet','recheck'), 'router-review': ('router',)}
SCENARIO_GUIDES = {'CPE_UNREACHABLE':'cpe-offline','PERFORMANCE_DEGRADED':'router-review'}
PHOTO_CAPTIONS = {
    "en": "AI-generated generic example, not verified ISP equipment. Labels and connections may be inaccurate; this is not a wiring guide.",
    "es": "Ejemplo genérico generado con IA, no verificado para equipos del ISP. Las etiquetas y conexiones pueden ser inexactas; no es una guía de cableado.",
}
GUIDES = {
    "poe": (1, "poe_injector", ("Locate your PoE injector", "Localiza tu inyector PoE"),
            ("Look for a separate adapter along the accessible cable route. A router or modem is not the same as a PoE injector or outdoor CPE. If unsure, send a photo rather than guessing.", "Busca un adaptador separado en el recorrido accesible del cable. Un router o módem no es lo mismo que un inyector PoE o una CPE exterior. Si tienes dudas, envía una foto sin adivinar.")),
    "lights": (2, "poe_injector", ("Check the power indicator", "Revisa el indicador de alimentación"),
               ("If your device has a visible power indicator, observe it without opening the case. Consult the actual model manual for its meaning. A lit light does not prove Internet access.", "Si el equipo tiene un indicador visible, obsérvalo sin abrir la carcasa. Consulta su significado en el manual del modelo real. Una luz encendida no demuestra acceso a Internet.")),
    "ethernet": (3, "ethernet_cable", ("Inspect accessible Ethernet connections", "Inspecciona las conexiones Ethernet accesibles"),
                 ("Visually inspect accessible cables and connectors for obvious damage. Do not disconnect unfamiliar wiring or assign ports using this generic guide.", "Inspecciona visualmente cables y conectores accesibles buscando daños evidentes. No desconectes cableado desconocido ni identifiques puertos con esta guía genérica.")),
    "recheck": (4, "generic_network", ("Let us check your connection again", "Volvamos a comprobar tu conexión"),
                ("Tell the assistant which accessible checks you completed. We can repeat the simulated connection check and request technical review if the issue persists.", "Cuéntale al asistente qué comprobaciones accesibles realizaste. Podemos repetir la comprobación simulada de conexión y solicitar revisión técnica si persiste la falla.")),
    "router": (1, "router", ("Find your router", "Localiza tu router"),
               ("Observe the router and accessible connections. This illustration does not specify port assignments or indicator meanings.", "Observa el router y conexiones accesibles. Esta ilustración no define asignaciones de puertos ni significados de indicadores.")),
}


def catalog(language: str) -> list[dict]:
    index = 0 if language == "en" else 1
    entries = [{
        "id": f"{topic}-{language}", "title": titles[index], "guide_id": "cpe-offline" if topic != "router" else "router-review",
        "step_number": step, "description": descriptions[index], "descriptions": {"en": descriptions[0], "es": descriptions[1]},
        "alt_text": titles[index] + (" — generic demo equipment" if language == "en" else " — equipo genérico de demostración"),
        "language": language, "equipment_type": equipment, "compatible_equipment": ["DEMO-GENERIC"],
        "vendor_compatibility": ["generic_demo"], "model_compatibility": ["DEMO-GENERIC"],
        "safety_instructions": "Stay on the ground. Do not open power supplies, climb roofs, move antennas or handle electrical wiring." if language == "en" else "Permanece en el suelo. No abras fuentes de alimentación, subas al techo, muevas antenas ni manipules instalaciones eléctricas.",
        "path": f"demo_photos/{PHOTO_ASSETS[topic]}" if topic in ('poe','lights','ethernet') else f"{topic}-{language}.svg",
        "url": reverse("api:instruction-image", args=[f"{topic}-{language}"]),
        "mime_type": "image/jpeg" if topic in ('poe','lights','ethernet') else "image/svg+xml",
        "source": "original_demo", "license": "CC0-1.0",
    } for topic, (step, equipment, titles, descriptions) in GUIDES.items()]
    for entry in entries:
        topic = entry['id'].rsplit('-', 1)[0]
        if topic not in PHOTO_ASSETS:
            continue
        caption = PHOTO_CAPTIONS[language]
        entry.update({
            "path": f"demo_photos/{PHOTO_ASSETS[topic]}", "mime_type": "image/jpeg",
            "source": "supplied_ai_generated_demo", "license": "demo_use_authorized_by_user",
            "production_approved": False, "verified_model": None, "caption": caption,
            "alt_text": entry['title'] + (" — AI-generated generic example" if language == 'en' else " — ejemplo genérico generado con IA"),
            "description": entry['description'] + ' ' + caption,
            "descriptions": {key: value + ' ' + PHOTO_CAPTIONS[key] for key, value in entry['descriptions'].items()},
        })
    return entries


def find_instruction(image_id: str):
    return next((item for language in ("es", "en") for item in catalog(language) if item["id"] == image_id), None)


def relevant_images(result_code: str | None, language: str) -> list[dict]:
    # Radio: revisión técnica sin guía CPE. Rendimiento: revisión local genérica del router.
    topics = GUIDE_TOPICS.get(SCENARIO_GUIDES.get(result_code), ())
    entries = {item["id"]: item for item in catalog(language)}
    selected = [entries[f"{topic}-{language}"] for topic in topics]
    if any(not (ASSET_ROOT / item['path']).is_file() for item in selected):
        logging.getLogger(__name__).warning('Approved guide asset unavailable; guide omitted')
        return []
    return selected


def catalog_errors():
    errors = []
    expected = [('poe','poe_locate_demo.jpg'),('lights','poe_power_indicator_demo.jpg'),('ethernet','ethernet_inspection_demo.jpg'),('recheck',None)]
    for language in ('en','es'):
        entries = {item['id']:item for item in catalog(language)}
        for number,(topic,filename) in enumerate(expected,1):
            entry = entries[f'{topic}-{language}']
            path = f'demo_photos/{filename}' if filename else f'recheck-{language}.svg'
            mime = 'image/jpeg' if filename else 'image/svg+xml'
            if (entry['step_number'],entry['path'],entry['mime_type']) != (number,path,mime):
                errors.append(f'Invalid mapping: {entry["id"]}')
            asset = ASSET_ROOT / path
            if not asset.is_file():
                errors.append(f'Missing asset: {entry["id"]}')
            elif filename and not asset.read_bytes().startswith(b'\xff\xd8\xff'):
                errors.append(f'Invalid JPEG: {entry["id"]}')
    return errors
