# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import os

datas = []
binaries = []
hiddenimports = [
    'api.routers.keyword_search_api2',
    'database_package',  # database_package.py를 직접 포함
    'models',
    'api.routers.keyword_search',
    'utils.auth_helpers',
    'sqlalchemy.dialects.mysql.pymysql',
    'tkinter',
    'tkinter.ttk',
    'tkinter.messagebox',
    'tkinter.scrolledtext',
    'concurrent.futures',
    'queue',
    'threading'
]

# Selenium 관련 수집
tmp_ret = collect_all('selenium')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

# WebDriver Manager 관련 수집
tmp_ret = collect_all('webdriver_manager')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

a = Analysis(
    ['manual_multitag_crawling.py'],
    pathex=[os.path.abspath('.')],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# database_package 모듈이 제대로 포함되었는지 확인
database_package_found = False
for mod in a.pure:
    try:
        mod_name = getattr(mod, 'name', None) or str(mod)
        if 'database_package' in mod_name.lower():
            database_package_found = True
            print(f"INFO: database_package 모듈을 찾았습니다: {mod_name}")
            break
    except:
        pass

if not database_package_found:
    print("WARNING: database_package 모듈이 Analysis에 포함되지 않았습니다!")
    print("INFO: hiddenimports에 'database_package'가 포함되어 있으므로 패키징 시 포함될 것입니다.")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='manual_multitag_crawling',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 아이콘 파일이 있으면 경로 지정 가능
)
