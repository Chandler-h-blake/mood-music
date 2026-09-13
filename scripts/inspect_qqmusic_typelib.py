from __future__ import annotations

import argparse
import ctypes
import json
import winreg
from ctypes import wintypes
from pathlib import Path

REGKIND_NONE = 2
TYPELIB_REGISTRY_KEY = (
    r"SOFTWARE\Classes\WOW6432Node\TypeLib"
    r"\{C4549B07-549D-46C4-AAF6-49CC54B99F69}\1.0\0\win32"
)


def _registered_typelib_path() -> Path:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, TYPELIB_REGISTRY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "")
    except OSError as error:
        raise SystemExit("QQMusicSvr 1.0 type library is not registered") from error
    return Path(value)


def _method(pointer: ctypes.c_void_p, index: int, restype: object, *argtypes: object):
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    address = vtable[index]
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(address)


def _take_bstr(value: ctypes.c_void_p | int | None) -> str | None:
    address = value.value if isinstance(value, ctypes.c_void_p) else value
    if not address:
        return None
    try:
        return ctypes.wstring_at(address)
    finally:
        ctypes.windll.oleaut32.SysFreeString(ctypes.c_void_p(address))


def _documentation(type_info: ctypes.c_void_p, member_id: int) -> tuple[str | None, str | None]:
    name = ctypes.c_void_p()
    description = ctypes.c_void_p()
    help_context = wintypes.DWORD()
    help_file = ctypes.c_void_p()
    get_documentation = _method(
        type_info,
        12,
        wintypes.LONG,
        wintypes.LONG,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(ctypes.c_void_p),
    )
    result = get_documentation(
        type_info,
        member_id,
        ctypes.byref(name),
        ctypes.byref(description),
        ctypes.byref(help_context),
        ctypes.byref(help_file),
    )
    if result != 0:
        return None, None
    member_name = _take_bstr(name)
    member_description = _take_bstr(description)
    _take_bstr(help_file)
    return member_name, member_description


def _member_names(type_info: ctypes.c_void_p, member_id: int) -> list[str]:
    values = (ctypes.c_void_p * 32)()
    count = wintypes.UINT()
    get_names = _method(
        type_info,
        7,
        wintypes.LONG,
        wintypes.LONG,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.UINT,
        ctypes.POINTER(wintypes.UINT),
    )
    result = get_names(type_info, member_id, values, len(values), ctypes.byref(count))
    if result != 0:
        return []
    return [name for index in range(count.value) if (name := _take_bstr(values[index]))]


def inspect_type_info(type_info: ctypes.c_void_p) -> dict:
    interface_name, _ = _documentation(type_info, -1)
    get_func_desc = _method(
        type_info,
        5,
        wintypes.LONG,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p),
    )
    release_func_desc = _method(type_info, 20, None, ctypes.c_void_p)
    members = []
    for index in range(256):
        descriptor = ctypes.c_void_p()
        result = get_func_desc(type_info, index, ctypes.byref(descriptor))
        if result != 0:
            break
        try:
            member_id = ctypes.cast(descriptor, ctypes.POINTER(wintypes.LONG)).contents.value
            names = _member_names(type_info, member_id)
            name, description = _documentation(type_info, member_id)
            members.append(
                {
                    "memberId": member_id,
                    "name": name or (names[0] if names else None),
                    "parameters": names[1:] if len(names) > 1 else [],
                    "description": description,
                }
            )
        finally:
            release_func_desc(type_info, descriptor)
    return {"name": interface_name, "members": members}


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect the registered QQMusic type library")
    parser.add_argument("path", nargs="?", type=Path)
    arguments = parser.parse_args()
    typelib_path = arguments.path or _registered_typelib_path()
    if not typelib_path.is_file():
        raise SystemExit(f"QQMusic type library not found: {typelib_path}")

    oleaut32 = ctypes.windll.oleaut32
    type_library = ctypes.c_void_p()
    result = oleaut32.LoadTypeLibEx(
        str(typelib_path), REGKIND_NONE, ctypes.byref(type_library)
    )
    if result != 0:
        raise OSError(result, "LoadTypeLibEx failed")

    try:
        get_count = _method(type_library, 3, wintypes.UINT)
        get_type_info = _method(
            type_library,
            4,
            wintypes.LONG,
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p),
        )
        release = _method(type_library, 2, wintypes.ULONG)
        interfaces = []
        for index in range(get_count(type_library)):
            type_info = ctypes.c_void_p()
            if get_type_info(type_library, index, ctypes.byref(type_info)) != 0:
                continue
            try:
                inspected = inspect_type_info(type_info)
                if inspected["name"] and inspected["members"]:
                    interfaces.append(inspected)
            finally:
                _method(type_info, 2, wintypes.ULONG)(type_info)
        print(
            json.dumps(
                {
                    "typeLibrary": "QQMusicSvr 1.0",
                    "source": str(typelib_path),
                    "interfaces": interfaces,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        release(type_library)


if __name__ == "__main__":
    main()
