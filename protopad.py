from google.protobuf import json_format
from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.message import DecodeError
import argparse
import pkgutil
import json
import os
import shutil
import subprocess
import sys


DOTFILE_PATH = os.path.expanduser("~/.protopad/config.json")
TEMPFILE_PATH = os.path.expanduser("~/.protopad/temp.json")


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def fail(status, message):
    eprint("protopad: " + message)
    exit(status)


def parse_proto_or_fail(proto, binary, message):
    try:
        proto.ParseFromString(binary)
    except DecodeError:
        fail(1, message)


def get_json_name(pyname):
    if "_" not in pyname:
        return pyname

    words = pyname.split("_")
    late_words = [w.capitalize() for w in words[1:]]
    words = [words[0]] + late_words
    return "".join(words)


def protopad(args):
    app = Protopad(args["verbose"])

    message_desc = app.get_message_desc(
        args["type"]) if "type" in args else None
    internal_type = args.get("internal_type")
    internal_desc = app.get_message_desc(
        internal_type) if internal_type else None

    command = args["task"]
    if command == "json":
        app.read_to_json(message_desc, internal_desc,
                         args.get("file"), args.get("output"))
    elif command == "proto":
        app.read_to_proto(message_desc, internal_desc,
                          args.get("file"), args.get("output"))
    elif command == "edit":
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            fail(1, "Cannot use terminal pipes with the edit command.\n"
                    "Use the `file` and `--output` parameters instead.")
        app.edit_message(message_desc, internal_desc, args.get("file"), args.get(
            "output"), args["empty"], args["recent"], args.get("editor"))
    elif command == "register":
        if args["list"]:
            app.list_registered_paths()
        elif args["recompile"]:
            app.recompile_protos()
        else:
            app.register_proto_path(args["path"], args["remove"])
    else:
        assert False, "Unreachable code!"


class Protopad:
    def __init__(self, verbose=False):
        self.verbose = verbose

    def log(self, text, always=False):
        if self.verbose or always:
            eprint(text)

    def get_message_desc(self, message_type_name):
        split_name = message_type_name.rsplit(".", 1)
        message_type_name = split_name[-1]
        prefix = split_name[0] if len(split_name) > 1 else ""

        import_path = os.path.expanduser("~/.protopad/compiled")
        options = []
        for loader, module_name, is_pkg in pkgutil.walk_packages([import_path]):
            try:
                self.log(f"Loading module: {module_name}")
                module = loader.find_module(
                    module_name).load_module(module_name)
                descriptor = getattr(module, "DESCRIPTOR", None)
                if descriptor:
                    for message_type, message_desc in descriptor.message_types_by_name.items():
                        self.log(f"  Found message type: {message_type}")
                        options.append(
                            (message_type, message_desc, module_name))
                else:
                    self.log(f"  No descriptor in module.")
            except AssertionError:
                self.log(f"  (Module {module_name} could not be loaded.)")
                continue

        if not options:
            fail(1, "Failed to load any message types at all."
                    "Check your registered paths with `protopad register --list`")

        selection = [option
                     for option in options
                     if option[0] == message_type_name and prefix in option[2]]

        if not selection:
            fail(1, f"Unknown message type '{message_type_name}'")
        elif len(selection) > 1:
            eprint(
                f"Message type '{message_type_name}' is ambiguous. Possibilities are:")
            for (name, _, module_name) in selection:
                eprint(f"- {module_name}.{name}")
            fail(
                1, f"Add any unambiguous prefix to the type name to specify. (e.g. `prefix.TypeName`)")

        (_, desc, _) = selection[0]
        return desc

    def read_to_json(self, message_desc, internal_desc, infile, outfile):
        base = read_any_input(message_desc, internal_desc, infile)
        result = proto_to_json(base, internal_desc)

        if outfile:
            with open(outfile, "w") as f:
                f.write(result)
        else:
            print(result)

    def read_to_proto(self, message_desc, internal_desc, infile, outfile):
        base = read_any_input(message_desc, internal_desc, infile)
        result = base.SerializeToString()

        if outfile:
            with open(outfile, "wb") as f:
                f.write(result)
        else:
            sys.stdout.buffer.write(result)

    def edit_message(self, message_desc, internal_desc,
                     infile, outfile, empty, recent, editor_command):
        filename = TEMPFILE_PATH if recent else infile
        base = read_any_input(message_desc, internal_desc,
                              filename) if filename else create_template_message(message_desc, empty)

        # TODO: Use create_template_message for empty binary entries.
        json = proto_to_json(base, internal_desc,
                             including_default_value_fields=True)

        self.log("Launching editor... (quit editor when finished)")
        edited_json = interactive_edit_message(
            json, editor_command=editor_command)
        self.log("Done.")

        resulting_message = json_to_proto(
            edited_json, message_desc, internal_desc)
        result = resulting_message.SerializeToString()

        if outfile:
            with open(outfile, "wb") as f:
                f.write(result)
        else:
            sys.stdout.buffer.write(result)

    def list_registered_paths(self):
        with open(DOTFILE_PATH, "r") as f:
            config = json.load(f)

        paths = set(config.get("paths", []))
        for path in paths:
            print(path)

    def register_proto_path(self, path, remove):
        path = os.path.abspath(path)
        assert path is not None
        action = "Unregistering" if remove else "Registering"
        self.log(f"{action} path: {path}")

        with open(DOTFILE_PATH, "r") as f:
            config = json.load(f)

        paths = set(config.get("paths", []))

        if remove:
            if path in paths:
                paths.remove(path)
            else:
                fail(
                    1, f"The path `{path}` is not registered and so can't be removed.")
        else:
            paths.add(path)

        self.log("Updated paths:")
        for path in paths:
            self.log(f"- {path}")

        paths = config["paths"] = list(paths)

        with open(DOTFILE_PATH, "w") as f:
            json.dump(config, f)

        self.recompile_protos()

    def recompile_protos(self):
        self.log("Recompiling proto definitions...")
        with open(DOTFILE_PATH, "r") as f:
            config = json.load(f)

        paths = set(config.get("paths", []))

        output_dir = os.path.expanduser("~/.protopad/compiled")
        shutil.rmtree(output_dir, ignore_errors=True)
        os.makedirs(output_dir)

        errors = []

        for path in paths:
            for (dirpath, _, filenames) in os.walk(path):
                self.log(f"  Compiling modules in {dirpath}")
                for filename in filenames:
                    if os.path.splitext(filename)[1] == ".proto":
                        filename = os.path.join(dirpath, filename)
                        command = ["protoc", "-I", path,
                                   "--python_out", output_dir, filename]
                        command_string = " ".join(command)
                        self.log(f"    Executing: {command_string}")

                        output = subprocess.run(
                            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                        failed = output.returncode != 0
                        if output.stdout:
                            if failed:
                                message = f"    Failed: {command_string} {output.returncode}"
                                errors.append(message)
                                self.log(message)
                            lines = output.stdout.decode().splitlines()
                            for line in lines:
                                message = f"      (protoc) {line}"
                                if failed:
                                    errors.append(message)
                                self.log(message)

        if errors:
            eprint("  Compilation failed:")
            for error in errors:
                eprint(error)
            fail(1, "protopad: Compilation failed for the above proto files.")
        else:
            self.log("Done.")

        self.log("")
        self.generate_module_roots()

    def generate_module_roots(self):
        self.log("Generating module roots...")
        dirs = []
        compiled_dir = os.path.expanduser("~/.protopad/compiled")
        for (dirpath, _, _) in os.walk(compiled_dir):
            self.log(f"  Creating module root in {dirpath}")
            rootpath = os.path.join(dirpath, "__init__.py")
            open(rootpath, "a").close()
        self.log("Done.")


def read_any_input(message_desc, internal_desc, filename=None):
    if filename:
        with open(filename, "rb") as f:
            data = f.read()
    else:
        data = sys.stdin.buffer.read()

    return parse_any_input(data, message_desc, internal_desc)


def parse_any_input(data, message_desc, internal_desc):
    try:
        json = data.decode("utf-8")
        return json_to_proto(json, message_desc, internal_desc)
    except:
        base = message_desc._concrete_class()
        parse_proto_or_fail(base, data,
                            f"Failed to decode input as the message type `{message_desc.name}`. The data may be of another message type.")
        return base


def json_to_proto(json, message_desc, internal_desc):
    base = message_desc._concrete_class()
    (doctored_json, internals) = extract_internal_protos(json, base, internal_desc)
    json_format.Parse(doctored_json, base)
    if internals:
        reinstate_internals(internals, base)
    return base


def proto_to_json(message, internal_desc, including_default_value_fields=False):
    json_encoded = json_format.MessageToJson(
        message,
        including_default_value_fields=including_default_value_fields)

    if internal_desc is None:
        return json_encoded

    data = json.loads(json_encoded)

    def unpack_internals(desc, message, obj):
        for field in desc.fields:
            json_field_name = get_json_name(field.name)
            if field.type == FieldDescriptor.TYPE_BYTES:
                internal_bytes = getattr(message, field.name)
                obj.pop(json_field_name)
                internal_message = internal_desc._concrete_class()
                parse_proto_or_fail(internal_message, internal_bytes,
                                    f"Failed to decode internal type as {internal_desc.name}.")
                internal_message_json = json_format.MessageToJson(
                    internal_message,
                    including_default_value_fields=including_default_value_fields)
                obj[json_field_name] = json.loads(internal_message_json)
            elif field.message_type:
                unpack_internals(field.message_type, getattr(
                    message, field.name), obj[json_field_name])

    unpack_internals(message.DESCRIPTOR, message, data)

    return json.dumps(data, indent=2)


def extract_internal_protos(json_string, base_message, internal_desc):
    if internal_desc is None:
        return (json_string, None)

    def extract_internals(desc, obj, internals, path):
        for field in desc.fields:
            field_path = path + [field.name]
            json_field_name = get_json_name(field.name)
            if field.type == FieldDescriptor.TYPE_BYTES:
                internal_obj = obj.pop(json_field_name)
                internal_json = json.dumps(internal_obj)
                internal_base = internal_desc._concrete_class()
                internal_message = json_format.Parse(
                    internal_json, internal_base)
                internals.append((field_path, internal_message))
            elif field.message_type:
                extract_internals(field.message_type,
                                  obj[json_field_name], internals, field_path)

    desc = base_message.DESCRIPTOR
    data = json.loads(json_string)
    internals = []
    extract_internals(desc, data, internals, [])

    return (json.dumps(data), internals)


def reinstate_internals(internals, message):
    for path, internal_message in internals:
        binary = internal_message.SerializeToString()
        target = message
        for field_name in path[:-1]:
            target = getattr(target, field_name)
        setattr(target, path[-1], binary)


def interactive_edit_message(message_json, editor_command=None):
    editor = editor_command if editor_command else os.environ["EDITOR"]

    with open(TEMPFILE_PATH, "w") as f:
        f.write(message_json)

    result = subprocess.run(f"{editor} {TEMPFILE_PATH}", shell=True)

    with open(TEMPFILE_PATH, "r") as f:
        edited_result = f.read()

    return edited_result


def create_template_message(message_descriptor, empty):
    message_class = message_descriptor._concrete_class
    base = message_class()
    if not empty:
        for field in message_descriptor.fields:
            if field.message_type:
                if field.label == FieldDescriptor.LABEL_REPEATED:
                    placeholder_value = create_template_message(
                        field.message_type, False)
                    field_container = getattr(base, field.name, None)
                    try:
                        # Repeated type
                        dest = field_container.add()
                        dest.MergeFrom(placeholder_value)
                    except AttributeError:
                        # Map type - leave blank for now
                        pass
                else:
                    getattr(base, field.name).MergeFrom(
                        create_template_message(field.message_type, False))
    return base


def ensure_dotfiles_exist():
    os.makedirs(os.path.expanduser("~/.protopad/compiled"), exist_ok=True)
    if not os.path.exists(DOTFILE_PATH):
        with open(DOTFILE_PATH, "w") as f:
            json.dump({}, f)


def main():
    from google.protobuf import __version__ as protobuf_version
    major, minor, _ = [int(part) for part in protobuf_version.split(".")]
    if major < 3 or minor < 6:
        eprint(
            f"protopad: Incompatible version of protobuf installed: {protobuf_version}. Requires at least version 3.6.0.")
        eprint("protopad: Try running `pip install -r requirements.txt` in the protopad repo to install the correct version.")
        exit(1)

    ensure_dotfiles_exist()

    parser = argparse.ArgumentParser(
        prog="protopad",
        description="create protobuf files from the terminal")

    parser.add_argument(
        "--verbose", "-v", help="enable verbose logging", action="store_true")
    parser.add_argument(
        "--version", "-V", action="version", version="0.9.0")

    subparsers = parser.add_subparsers(help="subcommands")

    # json command
    json_cmd_parser = subparsers.add_parser(
        "json", help="read a JSON or protobuf message and output JSON")
    json_cmd_parser.set_defaults(task="json")
    json_cmd_parser.add_argument(
        "file", help="the file to read, or stdin if not specified", nargs="?")
    json_cmd_parser.add_argument(
        "--output", "-o", help="a file to write to, or stdout if not specified")
    json_cmd_parser.add_argument(
        "--type", "-t", help="the protobuf message type", required=True)
    json_cmd_parser.add_argument(
        "--internal-type", "-i", help="the protobuf message type represented by any bytes-type fields, if any")

    # proto command
    proto_cmd_parser = subparsers.add_parser(
        "proto", help="read a JSON or protobuf message and output protobuf")
    proto_cmd_parser.set_defaults(task="proto")
    proto_cmd_parser.add_argument(
        "file", help="the file to read, or stdin if not specified", nargs="?")
    proto_cmd_parser.add_argument(
        "--output", "-o", help="a file to write to, or stdout if not specified")
    proto_cmd_parser.add_argument(
        "--type", "-t", help="the protobuf message type", required=True)
    proto_cmd_parser.add_argument(
        "--internal-type", "-i", help="the protobuf message type represented by any bytes-type fields, if any")

    # edit command
    # TODO: Fix pipes?
    edit_cmd_parser = subparsers.add_parser(
        "edit", help="create or edit a protobuf message in an editor")
    edit_cmd_parser.set_defaults(task="edit")
    edit_group = edit_cmd_parser.add_mutually_exclusive_group()
    edit_group.add_argument(
        "file", help="an input file to use as a template, or a default message if not specified", nargs="?")
    edit_group.add_argument(
        "--empty", "-e",
        help="use a completely empty message instead of the default",
        action="store_true")
    edit_group.add_argument(
        "--recent", help="use the most recent edit as a template",
        action="store_true")
    edit_cmd_parser.add_argument(
        "--output", "-o", help="a file to write to, or stdout if not specified", required=True)
    edit_cmd_parser.add_argument(
        "--type", "-t", help="the protobuf message type", required=True)
    edit_cmd_parser.add_argument(
        "--internal-type", "-i", help="the protobuf message type represented by any bytes-type fields, if any")
    edit_cmd_parser.add_argument(
        "--editor", help="the editor command to use, or $EDITOR by default")

    # register command
    register_cmd_parser = subparsers.add_parser(
        "register", help="register a folder of protobuf definitions")
    register_cmd_parser.set_defaults(task="register")
    register_group = register_cmd_parser.add_mutually_exclusive_group(
        required=True)
    register_group.add_argument(
        "path", help="path to a folder containing protobuf definitions (searched recursively)", nargs="?")
    register_group.add_argument(
        "--list", "-l", help="list the paths that are currently registered",
        action="store_true")
    register_group.add_argument(
        "--recompile", "-c",
        help="recompiles registered proto definitions (this happens automatically when registering)",
        action="store_true")
    register_cmd_parser.add_argument(
        "--remove", "-r", help="un-register this path",
        action="store_true")

    args = vars(parser.parse_args())
    if "task" not in args:
        parser.print_help()
        exit(2)
    protopad(args)
