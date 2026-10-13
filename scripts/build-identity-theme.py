"""Generate Keycloak classes from the actual shared shadcn controls.
Run before Vite build; --css copies its compiled stylesheet after the build.
No independent palette or hand-maintained input/button styles.
"""
import re
import shutil
import sys
import json
import subprocess
import hashlib
from pathlib import Path
root = Path(__file__).resolve().parents[1]
target = root / "identity/themes/actvero/login"
target.mkdir(parents=True, exist_ok=True)
if "--css" in sys.argv or "--version" in sys.argv:
    destination = target / "resources/css/generated.css"
    if "--css" in sys.argv:
        styles = list((root / "frontend/dist/assets").glob("index-*.css"))
        if len(styles) != 1: raise SystemExit("Expected one compiled entry stylesheet")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(styles[0], destination)
    # Keycloak's resource path changes with its version, not our theme releases.
    # Give unchanged cached pages a new resource URL whenever our CSS/JS changes.
    version = hashlib.sha256(destination.read_bytes() + b"\0" + (target / "resources/js/actvero.js").read_bytes()).hexdigest()[:16]
    properties_path = target / "theme.properties"
    properties_text = re.sub(r"^actveroThemeVersion=.*\n?", "", properties_path.read_text(), flags=re.M)
    properties_path.write_text(properties_text.rstrip() + "\nactveroThemeVersion=" + version + "\n")
    print("身份页面已同步统一主题及资源版本。")
    raise SystemExit(0)
source = (root / "frontend/src/components/ui/input.tsx").read_text()
input_classes = " ".join(re.findall(r"'([^'\n]+)'", source.split("className={cn(")[1].split("className")[0]))
source = (root / "frontend/src/components/ui/button.tsx").read_text()
base = re.search(r'cva\(\s*"([^"]+)"', source).group(1)
variant = re.search(r"default:\s*'([^']+)'", source).group(1)
size = re.search(r"size:\s*\{\s*default:\s*'([^']+)'", source).group(1)
button = base + " " + variant + " " + size
secondary = base + " " + re.search(r"outline:\s*'([^']+)'", source).group(1) + " " + size
password_source = (root / "frontend/src/components/password-input.tsx").read_text()
position = re.search(r"className='(absolute[^']+)'", password_source).group(1)
password_toggle = base + " " + re.search(r"ghost:\s*'([^']+)'", source).group(1) + " size-9 " + position
checkbox_source = (root / "frontend/src/components/ui/checkbox.tsx").read_text()
checkbox_classes = re.search(r"className=\{cn\(\s*'([^']+)'", checkbox_source).group(1).replace('data-[state=checked]:', 'checked:') + ' appearance-none'
icons = subprocess.run(['node', '--input-type=module', '-e', "import React from 'react'; import {renderToStaticMarkup} from 'react-dom/server'; import {Eye,EyeOff,Check,UserRound} from 'lucide-react'; console.log(JSON.stringify([Eye,EyeOff,Check,UserRound].map(icon=>renderToStaticMarkup(React.createElement(icon,{className:'size-4', 'aria-hidden':true})))));"], cwd=root/'frontend', check=True, capture_output=True, text=True)
eye, eye_off, check, user_icon = json.loads(icons.stdout)
(target/'icons.ftl').write_text('<#macro eye>'+eye+'</#macro>\n<#macro eyeOff>'+eye_off+'</#macro>\n<#macro check>'+check+'</#macro>\n<#macro user>'+user_icon+'</#macro>\n')
geometry = json.loads((root / "frontend/src/assets/brand/geometry.json").read_text())
view_box = ' '.join(str(value) for value in geometry['viewBox'])
paths = f'<path d="{geometry["path"]}"/><path d="{geometry["path"]}" transform="{geometry["secondPartTransform"]}"/>'
logo = f'<svg viewBox="{view_box}" fill="currentColor" class="size-6" aria-hidden="true" data-actvero-brand="mark">{paths}</svg>'
with (target/'icons.ftl').open('a') as file:
    file.write('<#macro logo>'+logo+'</#macro>\n')
# The same local brand geometry drives the React mark, identity theme and favicon.
public = root / 'frontend/public'
brand = public / 'brand'
brand.mkdir(parents=True, exist_ok=True)
favicon = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}"><title>Actvero</title><style>path{{fill:{geometry["colors"]["ink"]}}}@media(prefers-color-scheme:dark){{path{{fill:{geometry["colors"]["white"]}}}}}</style>{paths}</svg>\n'
(brand / 'actvero-mark.svg').write_text(favicon)
identity_images = target / 'resources/img'
identity_images.mkdir(parents=True, exist_ok=True)
for asset in (brand / 'actvero-mark.svg', brand / 'actvero-icon.png', public / 'favicon.ico'):
    shutil.copyfile(asset, identity_images / asset.name)
card_source = (root / "frontend/src/components/ui/card.tsx").read_text()
card = re.search(r"className=\{cn\(\s*'([^']+)'", card_source).group(1)
properties = {
 "parent": "keycloak", "import": "common/keycloak",
 "styles": "css/generated.css", "scripts": "js/actvero.js",
 "kcInputClass": input_classes,
 "kcCardClass": card,
 "kcAccountCardClass": card.replace("py-6", "py-4").replace("gap-6", "gap-0"),
 "kcButtonClass": button, "kcButtonPrimaryClass": "", "kcButtonDefaultClass": "",
 "kcButtonLargeClass": "", "kcButtonBlockClass": "w-full", "kcButtonSecondaryClass": "",
 "kcCheckboxClass": checkbox_classes, "kcPasswordToggleClass": password_toggle, "kcSecondaryButtonClass": secondary,
 "kcFormClass": "flex flex-col gap-4",
 "kcFormGroupClass": "flex flex-col gap-2",
 "kcLabelClass": "text-sm font-medium",
 "kcInputErrorMessageClass": "text-sm text-destructive",
 "kcFormPasswordVisibilityButtonClass": base + " border border-input bg-background px-3",
 "kcInputGroup": "flex items-center gap-2",
 "kcFormButtonsClass": "mt-4",
 "kcFormOptionsClass": "text-sm text-muted-foreground",
 "kcFormOptionsWrapperClass": "text-sm text-muted-foreground",
 "kcInputWrapperClass": "flex flex-col gap-2",
 "kcFormSettingClass": "flex flex-col gap-4",
}
(target / "theme.properties").write_text("# Generated from shared components; do not hand-edit.\n".replace("\\n","\n") + "\n".join(k + "=" + v for k,v in properties.items()) + "\n")
