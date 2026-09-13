from __future__ import annotations

import argparse
import ctypes
import json
import uuid
import winreg
from ctypes import wintypes
from pathlib import Path

REGKIND_NONE = 2
TYPELIB_REGISTRY_KEY = (
    r"SOFTWARE\Classes\WOW6432Node\TypeLib"
    r"\{C4549B07-549D-46C4-AAF6-49CC54B99F69}\1.0\0\win32"
)


class GUID(ctypes.Structure):
    _fields_ = [
        ("data1", wintypes.DWORD),
        ("data2", wintypes.WORD),
        ("data3", wintypes.WORD),
        ("data4", ctypes.c_ubyte * 8),
    ]


class TYPEATTR_HEADER(ctypes.Structure):
    _fields_ = [
        ("guid", GUID),
        ("lcid", wintypes.DWORD),
        ("reserved", wintypes.DWORD),
        ("constructor", wintypes.LONG),
        ("destructor", wintypes.LONG),
        ("schema", ctypes.c_void_p),
        ("instance_size", wintypes.ULONG),
        ("type_kind", ctypes.c_int),
        ("function_count", wintypes.WORD),
        ("variable_count", wintypes.WORD),
        ("implemented_type_count", wintypes.WORD),
        ("vtable_size", wintypes.WORD),
    ]


TYPE_KIND_NAMES = {
    0: "enum",
    1: "record",
    2: "module",
    3: "interface",
    4: "dispatch",
    5: "coclass",
    6: "alias",
    7: "union",
}


class TYPEDESC(ctypes.Structure):
    pass


class TYPEDESC_VALUE(ctypes.Union):
    _fields_ = [
        ("nested", ctypes.POINTER(TYPEDESC)),
        ("reference", wintypes.DWORD),
    ]


TYPEDESC._fields_ = [("value", TYPEDESC_VALUE), ("variant_type", wintypes.WORD)]


class PARAMDESC(ctypes.Structure):
    _fields_ = [("extended", ctypes.c_void_p), ("flags", wintypes.WORD)]


class ELEMDESC(ctypes.Structure):
    _fields_ = [("type", TYPEDESC), ("parameter", PARAMDESC)]


class FUNCDESC(ctypes.Structure):
    _fields_ = [
        ("member_id", wintypes.LONG),
        ("status_codes", ctypes.c_void_p),
        ("parameters", ctypes.POINTER(ELEMDESC)),
        ("function_kind", ctypes.c_int),
        ("invoke_kind", ctypes.c_int),
        ("calling_convention", ctypes.c_int),
        ("parameter_count", ctypes.c_short),
        ("optional_parameter_count", ctypes.c_short),
        ("vtable_offset", ctypes.c_short),
        ("status_code_count", ctypes.c_short),
        ("return_value", ELEMDESC),
        ("flags", wintypes.WORD),
    ]


VARIANT_TYPE_NAMES = {
    0: "void",
    2: "int16",
    3: "int32",
    8: "bstr",
    11: "bool",
    12: "variant",
    13: "iunknown",
    19: "uint32",
    20: "int64",
    21: "uint64",
    22: "int",
    23: "uint",
    24: "void",
    25: "hresult",
    26: "pointer",
}


def _type_description(description: TYPEDESC) -> str:
    variant_type = int(description.variant_type)
    if variant_type == 26 and description.value.nested:
        return f"pointer<{_type_description(description.value.nested.contents)}>"
    return VARIANT_TYPE_NAMES.get(variant_type, f"variantType:{variant_type}")


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


def _type_identity(type_info: ctypes.c_void_p) -> tuple[str, int, int]:
    descriptor = ctypes.c_void_p()
    get_type_attr = _method(
        type_info, 3, wintypes.LONG, ctypes.POINTER(ctypes.c_void_p)
    )
    if get_type_attr(type_info, ctypes.byref(descriptor)) != 0:
        raise RuntimeError("ITypeInfo.GetTypeAttr failed")
    try:
        header = ctypes.cast(descriptor, ctypes.POINTER(TYPEATTR_HEADER)).contents
        guid = uuid.UUID(bytes_le=bytes(header.guid))
        return str(guid), header.type_kind, header.implemented_type_count
    finally:
        _method(type_info, 19, None, ctypes.c_void_p)(type_info, descriptor)


def _implemented_types(type_info: ctypes.c_void_p, count: int) -> list[dict]:
    get_reference = _method(
        type_info,
        8,
        wintypes.LONG,
        wintypes.UINT,
        ctypes.POINTER(wintypes.DWORD),
    )
    get_reference_info = _method(
        type_info,
        14,
        wintypes.LONG,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    )
    references = []
    for index in range(count):
        reference = wintypes.DWORD()
        if get_reference(type_info, index, ctypes.byref(reference)) != 0:
            continue
        reference_info = ctypes.c_void_p()
        if get_reference_info(type_info, reference, ctypes.byref(reference_info)) != 0:
            continue
        try:
            name, _ = _documentation(reference_info, -1)
            guid, type_kind, _ = _type_identity(reference_info)
            references.append(
                {
                    "name": name,
                    "guid": guid,
                    "typeKind": TYPE_KIND_NAMES.get(type_kind, str(type_kind)),
                }
            )
        finally:
            _method(reference_info, 2, wintypes.ULONG)(reference_info)
    return references


def inspect_type_info(type_info: ctypes.c_void_p) -> dict:
    interface_name, _ = _documentation(type_info, -1)
    guid, type_kind, implemented_type_count = _type_identity(type_info)
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
            function = ctypes.cast(descriptor, ctypes.POINTER(FUNCDESC)).contents
            member_id = function.member_id
            names = _member_names(type_info, member_id)
            name, description = _documentation(type_info, member_id)
            parameter_types = [
                {
                    "type": _type_description(function.parameters[item].type),
                    "flags": int(function.parameters[item].parameter.flags),
                }
                for item in range(function.parameter_count)
            ]
            members.append(
                {
                    "memberId": member_id,
                    "name": name or (names[0] if names else None),
                    "parameters": names[1:] if len(names) > 1 else [],
                    "parameterTypes": parameter_types,
                    "returnType": _type_description(function.return_value.type),
                    "vtableOffset": function.vtable_offset,
                    "callingConvention": function.calling_convention,
                    "description": description,
                }
            )
        finally:
            release_func_desc(type_info, descriptor)
    return {
        "name": interface_name,
        "guid": guid,
        "typeKind": TYPE_KIND_NAMES.get(type_kind, str(type_kind)),
        "implementedTypes": _implemented_types(type_info, implemented_type_count),
        "members": members,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a QQ Music type library")
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--name", action="append", dest="names")
    parser.add_argument(
        "--member",
        action="append",
        dest="members",
        help="Only include types exposing a member with this exact name",
    )
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
                member_names = {
                    member["name"] for member in inspected["members"] if member["name"]
                }
                if (
                    inspected["name"]
                    and (not arguments.names or inspected["name"] in arguments.names)
                    and (
                        not arguments.members
                        or any(member in member_names for member in arguments.members)
                    )
                ):
                    interfaces.append(inspected)
            finally:
                _method(type_info, 2, wintypes.ULONG)(type_info)
        print(
            json.dumps(
                {
                    "typeLibrary": typelib_path.stem,
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
