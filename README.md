# protopad

Edit and convert protobuf messages to and from JSON.

## Installation

1.  Install dependencies: `pip install -r requirements.txt`
2.  Add the `protopad` file to your path.
    -   For example by adding `export PATH="$PATH:/path/to/protopad"` to your .bashrc file

## Usage

```bash
$ protopad --help       # See help
$ protopad edit --help  # See help for specific command
```

### Registering protobuf definitions

You first need to register the protobuf definitions that you want to use with this tool.

For example, if you have protobuf definitions under `path/to/protos/package/*.proto`:

```bash
$ protopad register ~/path/to/protos
```

You can register multiple paths. To list the paths you've added already:

```bash
$ protopad register --list
```

They're compiled when first registered, but if the definitions change, you can recompile them with:

```bash
$ protopad register --recompile
```

To remove a path, add the `--remove` flag:

```bash
$ protopad register ~/path/to/protos --remove
```

### Converting files to JSON

You can pass either protobuf or JSON, and it will output in JSON.

```bash
$ protopad json my_protobuf_binary --type MessageType
$ protopad json my_file.json --type MessageType

$ protopad json my_protobuf_binary -t MessageType --output new_file.json
$ protopad json my_protobuf_binary -t MessageType > new_file.json

$ cat my_protobuf_binary | protopad json -t MessageType
```

If `MessageType` is ambiguous, you can resolve it by adding any unambiguous prefix. For example, if you have both `request.types.Data` and `response.types.Data`, you could use:

```bash
$ protopad json my_protobuf_binary -t request.Data
```

### Converting files to protobuf

You can pass either protobuf or JSON, and it will output protobuf.

```bash
$ protopad proto my_file.json -t MessageType
$ protopad proto my_protobuf_binary -t MessageType
$ protopad proto my_protobuf_binary -t package.MessageType

$ protopad proto my_file.json -t MessageType -o new_binary_file
$ protopad proto my_file.json -t MessageType > new_binary_file

$ cat my_file.json | protopad proto -t MessageType
```

### Editing files

The `edit` command allows you to open a JSON template in an editor, modify it, then output it as protobuf. By default the editor to open is taken from the `$EDITOR` environment variable, but you can also select your own command with the `--editor EDITOR` flag.

Note that you cannot use pipes and so the `-o` (or `--output`) flag is required.

```bash
$ protopad edit my_protobuf_binary -t MessageType -o new_binary_file
```

The above command will open the editor with the contents of `my_protobuf_binary` as JSON. You can edit it, save, and close the editor. The new contents will be converted to protobuf and saved to `new_binary_file`.

There are other variations:

```bash
# Edit a default instance of MessageType
$ protopad edit -t MessageType -o output

# Edit an empty instance of MessageType (all message-type fields empty)
$ protopad edit -t MessageType --empty -o output

# Edit with the contents of the most recently edited file
$ protopad edit -t MessageType --recent -o output
```

#### Editor commands

To use a specific editor, set one of these commands in your `$EDITOR` environment variable, or pass it as `--editor`:

1.  Vim: `vim`
2.  VSCode: `code -w`
    -   (The `-w` flag tells the terminal to wait until the file is closed.)
3.  Nano: `nano`

### Internal messages

The `json`, `proto`, and `edit` commands allow you to specify an `--internal-type` parameter. This tells the app to replace all `bytes` type fields in the main protobuf as serialized instances of another type.

For example, if you have the following protobuf definitions:

```proto
message ContainerType {
    bytes blob_data = 1;
    string blob_type = 2;
}

message ContentsType {
    string id = 1;
}
```

... and the following JSON:

```json
{
    "blobData": {
        "id": "contents_id"
    },
    "blobType": "contents"
}
```

You could parse/edit it with any of the following commands:

```bash
$ protopad json my_file.json --type ContainerType --internal-type ContentsType
$ protopad proto my_file.json --type ContentsType --internal-type ContentsType
$ protopad edit my_file.json --type ContentsType --internal-type ContentsType -o output

$ protopad edit my_file.json -t ContentsType -i ContentsType -o output
```

The `--internal-type` (or `-i`) flag is telling the app that the "real" type of `blob_data` is `ContentsType`. It automatically handles serialization between `ContentsType` and `bytes` as needed.

There are some limitations:

1.  It's not recursive. Internal types can't have other internal types.
2.  You can only specify one internal type.
3.  _All_ bytes-type fields in the message are substituted. If you have a mix of genuine bytes-type fields, and fields which are serialized messages, it will not work correctly.
