bl_info = {
    "name": "Wii Model Helper",
    "blender": (4, 0, 0),
    "category": "Cleanup-Export",
    "description": "Exported Wii Model .dae (from Switch Toolbox) cleanup and .glb export utility",
    "author": "Hat",
    "version": (1, 0, 1),
}

import bpy
import json
import os
import struct
import xml.etree.ElementTree as ET

def scale_scene(scale_factor):
    """Scale the entire scene by a factor."""
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH':
            obj.scale *= scale_factor

def parse_dae_for_wrap_modes(dae_file_path):
    """Parse the origin .dae file and extract wrap modes for each material."""
    tree = ET.parse(dae_file_path)
    root = tree.getroot()

    material_wrap_modes = {}

    for effect in root.findall(".//ns0:effect", namespaces={"ns0": "http://www.collada.org/2005/11/COLLADASchema"}):
        effect_id = effect.get("id", "")
        effect_name = effect_id.replace("Effect_", "")
        
        wrap_s = "REPEAT"
        wrap_t = "REPEAT"
        
        for sampler in effect.findall(".//ns0:sampler2D", namespaces={"ns0": "http://www.collada.org/2005/11/COLLADASchema"}):
            wrap_s_elem = sampler.find("ns0:wrap_s", namespaces={"ns0": "http://www.collada.org/2005/11/COLLADASchema"})
            wrap_t_elem = sampler.find("ns0:wrap_t", namespaces={"ns0": "http://www.collada.org/2005/11/COLLADASchema"})
            
            if wrap_s_elem is not None:
                wrap_s = wrap_s_elem.text.upper()
            if wrap_t_elem is not None:
                wrap_t = wrap_t_elem.text.upper()
        
        material_wrap_modes[effect_name] = (wrap_s, wrap_t)

    return material_wrap_modes
    
### Exporting .glb with original wraps

def parse_glb_for_json(glb_file_path):
    """Parse a .glb file and return the JSON chunk data as a Python dict."""
    with open(glb_file_path, 'rb') as glb_file:
        # Read the GLB header (magic, version, length)
        magic, version, length = struct.unpack('<III', glb_file.read(12))

        if magic != 0x46546C67:  # 'glTF' in ASCII
            raise ValueError("Invalid GLB file format")

        # Find chunks by reading the rest of the file
        chunks = []
        while glb_file.tell() < length:
            chunk_length, chunk_type = struct.unpack('<II', glb_file.read(8))
            chunk_data = glb_file.read(chunk_length)

            chunks.append({
                'length': chunk_length,
                'type': chunk_type,
                'data': chunk_data
            })

        # Look for the JSON chunk (type: 0x4E4F534A => 'JSON')
        json_chunk = next((chunk for chunk in chunks if chunk['type'] == 0x4E4F534A), None)
        if json_chunk is None:
            raise ValueError("No JSON chunk found in GLB file")

        # Return the JSON data as a Python dictionary
        json_data = json.loads(json_chunk['data'])
        return json_data, chunks

def modify_wrap_modes_in_json(json_data, material_wrap_modes):
    """Copy the wrap modes from material_wrap_modes to the JSON data"""
    wrap_mode_map = {
        "WRAP": 10497,  # GL_REPEAT
        "MIRROR": 33648,  # GL_MIRRORED_REPEAT
        "CLAMP": 33071,  # GL_CLAMP_TO_EDGE
        "BORDER": None,  # No direct equivalent
        "NONE": None,  # No wrap mode
    }

    # Iterate through the materials
    for material in json_data.get('materials', []):
        material_name = material.get('name', '')
        if material_name not in material_wrap_modes:
            continue

        wrap_s, wrap_t = material_wrap_modes[material_name]
        
        wrap_s_value = wrap_mode_map.get(wrap_s, 10497)  # Default to GL_REPEAT
        wrap_t_value = wrap_mode_map.get(wrap_t, 10497)  # Default to GL_REPEAT

        # Track images used in this material by looking at the nodes of the material
        used_images = set()
        for node in bpy.data.materials.get(material_name).node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                used_images.add(os.path.splitext(node.image.name)[0])

        for texture in json_data.get("textures", []):
            source_index = texture.get("source")
            if source_index is None:
                continue

            # Get the image name from the JSON data
            image_name = json_data["images"][source_index].get("name", "").strip()

            # Check if the image is used in the material by matching the base name
            if not any(image_name.startswith(used_image) for used_image in used_images):
                continue

            # Process the texture's sampler
            sampler_index = texture.get("sampler")
            if sampler_index is not None:
                sampler = json_data["samplers"][sampler_index]
                print(f"Existing sampler: {sampler}")
                
                # Check if the wrap modes are different, if so, create a new sampler
                if sampler.get("wrapS") != wrap_s_value or sampler.get("wrapT") != wrap_t_value:
                    # Check if the same wrap modes already exist in the samplers
                    found_existing_sampler = False
                    for existing_sampler in json_data["samplers"]:
                        if (existing_sampler.get("wrapS") == wrap_s_value and
                                existing_sampler.get("wrapT") == wrap_t_value):
                            # Use the existing sampler
                            texture["sampler"] = json_data["samplers"].index(existing_sampler)
                            found_existing_sampler = True
                            break
                    
                    if not found_existing_sampler:
                        # If no matching sampler found, create a new one
                        new_sampler = create_new_sampler(wrap_s_value, wrap_t_value, sampler)
                        json_data["samplers"].append(new_sampler)
                        texture["sampler"] = len(json_data["samplers"]) - 1
            else:
                # If no sampler exists, create a new one
                new_sampler = create_new_sampler(wrap_s_value, wrap_t_value)
                json_data["samplers"].append(new_sampler)
                texture["sampler"] = len(json_data["samplers"]) - 1

    return json_data

def create_new_sampler(wrap_s_value, wrap_t_value, sampler=None):
    """Helper function to create a new sampler."""
    return {
        'wrapS': wrap_s_value,
        'wrapT': wrap_t_value,
        'magFilter': sampler.get('magFilter', 9729) if sampler else 9729,
        'minFilter': sampler.get('minFilter', 9987) if sampler else 9987,
    }

def rebuild_glb_file(output_path, json_data, chunks):
    """Rebuild the .glb file with modified JSON data."""
    # Find the JSON chunk in the original chunks
    json_chunk = next((chunk for chunk in chunks if chunk['type'] == 0x4E4F534A), None) # Magic = "JSON"
    if json_chunk is None:
        raise ValueError("No JSON chunk found in GLB file")

    # Convert modified JSON data back to bytes
    new_json_data = json.dumps(json_data).encode('utf-8')

    # Replace the original JSON chunk with the new one
    json_chunk['data'] = new_json_data

    # Calculate the total length of the GLB file
    json_chunk_length = len(new_json_data) + 8  # 8 bytes for the chunk header (chunkLength + chunkType)
    binary_chunk_length = len(chunks[1]['data']) + 8  # Assuming the binary chunk is the second one

    total_length = 12 + json_chunk_length + binary_chunk_length  # header + JSON chunk + binary chunk

    # Rebuild the GLB file with updated JSON chunk
    with open(output_path, 'wb') as glb_file:
        # Write the header again
        glb_file.write(struct.pack('<III', 0x46546C67, 2, total_length))  # magic (glTF), version, length

        # Write the JSON chunk
        glb_file.write(struct.pack('<II', len(new_json_data), 0x4E4F534A))  # chunkLength, chunkType (0x4E4F534A for JSON)
        glb_file.write(new_json_data)

        # Write the binary chunk (assuming it's the second chunk)
        binary_chunk = chunks[1]
        glb_file.write(struct.pack('<II', len(binary_chunk['data']), binary_chunk['type']))  # chunkLength, chunkType
        glb_file.write(binary_chunk['data'])

    print(f"Rebuilt .glb file: {output_path}")

def export_glb_with_custom_wrap(directory, filename, dae_file_path):
    """Export .glb file with custom wrapS and wrapT properties for each texture."""
    material_wrap_modes = parse_dae_for_wrap_modes(dae_file_path)

    # Ensure filename ends with .glb
    filename = filename or "model"
    if not filename.endswith(".glb"):
        filename += ".glb"

    output_path = os.path.join(directory, filename)

    # Step 1: Export glTF as .glb (separate bin files and images)
    bpy.ops.export_scene.gltf(
        filepath=output_path,
        export_format='GLB',  # Export as .glb directly
    )

    # Step 2: Modify the .glb file (handle wrapS and wrapT properties)
    json_data, chunks = parse_glb_for_json(output_path)
    json_data = modify_wrap_modes_in_json(json_data, material_wrap_modes)

    # Step 3: Rebuild the .glb file with the modified JSON data
    rebuild_glb_file(output_path, json_data, chunks)

    print(f"Exported and modified .glb file to {output_path}")

### Texture reformatting

def scale_uvs_for_extended_texture(obj, wrap_s, wrap_t, original_width, original_height, new_width, new_height):
    """Rescale the UVs down to match the extended texture size."""
    scale_x = original_width / new_width if wrap_s == "MIRROR" else 1.0
    scale_y = original_height / new_height if wrap_t == "MIRROR" else 1.0

    # Ensure the mesh has UV layers
    if obj.type == 'MESH' and obj.data.uv_layers:
        # Check if the object is in Object Mode, and if not, raise a warning
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')  # Set to Object Mode
            bpy.context.view_layer.objects.active = obj  # Ensure the object is the active one
            bpy.ops.object.select_all(action='DESELECT')  # Deselect all objects
            obj.select_set(True)  # Select the object to avoid confusion
            bpy.context.view_layer.objects.active = obj
            print(f"Warning: {obj.name} must be in Object Mode to access UVs. Switching to Object Mode.")

        for uv_layer in obj.data.uv_layers:
            if not uv_layer.data:
                # If UV layer is empty, raise a warning
                bpy.ops.object.mode_set(mode='OBJECT')  # Make sure we're in Object Mode
                print(f"Warning: UV layer '{uv_layer.name}' has no data. Skipping.")
                continue  # Skip if the UV layer is empty

            for loop in obj.data.loops:
                uv = uv_layer.data[loop.index].uv
                uv.x *= scale_x
                uv.y *= scale_y


def process_texture_with_mirroring(image, wrap_s, wrap_t):
    """Extend texture based on MIRROR wrap modes and adjust UVs accordingly."""
    width, height = image.size[0], image.size[1]
    extend_x = wrap_s == "MIRROR"
    extend_y = wrap_t == "MIRROR"

    # Determine new dimensions
    new_width = width * (2 if extend_x else 1)
    new_height = height * (2 if extend_y else 1)

    # No changes needed if neither dimension requires mirroring
    if new_width == width and new_height == height:
        return image, new_width, new_height

    # Create a new image with extended boundaries
    extended_image = bpy.data.images.new(
        name=f"{image.name}_extended",
        width=new_width,
        height=new_height
    )

    # Access original pixel data
    image_pixels = list(image.pixels[:])  # Original texture data
    extended_pixels = [0] * new_width * new_height * 4  # New texture data (RGBA)

    # Fill the new image
    for y in range(height):
        for x in range(width):
            index = (y * width + x) * 4
            # Section 1: Original texture
            extended_index = (y * new_width + x) * 4
            extended_pixels[extended_index:extended_index + 4] = image_pixels[index:index + 4]

            # Section 2: Mirrored along X-axis
            if extend_x:
                mirror_x_index = (y * new_width + (2 * width - x - 1)) * 4
                extended_pixels[mirror_x_index:mirror_x_index + 4] = image_pixels[index:index + 4]

        # Section 3: Mirrored along Y-axis
        if extend_y:
            for x in range(new_width):
                source_x = x % width  # Use original width to loop texture
                mirror_y_index = ((2 * height - y - 1) * new_width + source_x) * 4
                extended_index = (y * new_width + x) * 4
                extended_pixels[mirror_y_index:mirror_y_index + 4] = extended_pixels[extended_index:extended_index + 4]

    # Assign the pixel data back to the new image
    extended_image.pixels = extended_pixels

    return extended_image, new_width, new_height


def process_and_assign_textures_with_mirroring(dae_file_path):
    """Process textures based on MIRROR wrap modes and extend as needed."""
    # Parse the material wrap modes from the DAE file
    material_wrap_modes = parse_dae_for_wrap_modes(dae_file_path)

    # Iterate over materials and apply changes to textures and UVs
    for material_name, (wrap_s, wrap_t) in material_wrap_modes.items():
        for obj in bpy.context.scene.objects:
            if obj.type == 'MESH' and obj.active_material and obj.active_material.name == material_name:
                for node in obj.active_material.node_tree.nodes:
                    if node.type == "TEX_IMAGE" and node.image:
                        if wrap_s != "WRAP" or wrap_t != "WRAP":
                            # Extend and process the texture
                            extended_image, new_width, new_height = process_texture_with_mirroring(node.image, wrap_s, wrap_t)
                            original_width, original_height = node.image.size[0], node.image.size[1]
                            
                            # Replace the original image with the extended one
                            original_image_name = node.image.name
                            original_image = node.image

                            # Delete the original image to avoid redundant files
                            bpy.data.images.remove(original_image)

                            # Rename the extended image to the original image's name
                            extended_image.name = original_image_name
                            node.image = extended_image  # Assign the extended image to the texture

                            # Scale UVs to match the new extended texture
                            scale_uvs_for_extended_texture(obj, wrap_s, wrap_t, original_width, original_height, new_width, new_height)

    print("Texture processing and UV reassignment completed.")

### UI

def ensure_absolute_path(file_path):
    """Ensure the given path is absolute. Resolves relative paths."""
    # If the path starts with `//`, it's relative to the Blender project file
    if file_path.startswith("//"):
        file_path = bpy.path.abspath(file_path)  # Resolve relative to the .blend file

    return file_path

class ExportGLBPanel(bpy.types.Panel):
    """Creates a Panel in the Object properties window"""
    bl_label = "Wii Model Helper"
    bl_idname = "OBJECT_PT_export_glb"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Wii Model Helper'

    def draw(self, context):
        layout = self.layout

        row = layout.row()
        row.label(text="Scale Convert units (m -> cm)", icon='INFO')
        row = layout.row()
        row.operator("export.fix_scaling", text="Fix Scaling (Scale by 0.01)")
        
        layout.separator()

        row = layout.row()
        row.label(text="Origin .dae file", icon='FILE')
        row = layout.row()
        row.prop(context.scene, "dae_file_path", text="DAE file")
        
        layout.separator()
        
        row = layout.row()
        row.label(text="Reformat/Fix textures", icon='TEXTURE')
        row = layout.row()
        row.operator("process.condense_textures", text="Strip Wraps")
        
        layout.separator()
        
        row = layout.row()
        row.label(text="Export .glb with wraps", icon='FILE')
        row = layout.row()
        row.label(text="Only use this if textures haven't been reformatted!")
        row = layout.row()
        row.prop(context.scene, "output_directory", text="Output Directory")
        row = layout.row()
        row.prop(context.scene, "output_filename", text="Output Filename (Optional)")
        row = layout.row()
        row.operator("export.glb_with_wraps", text="Export .glb with fixed wraps")

class CondenseWrapIntoTextureOperator(bpy.types.Operator):
    """Operator to condense MIRROR wrap modes into texture variants"""
    bl_idname = "process.condense_textures"
    bl_label = "Condense Wraps into the original texture"

    def execute(self, context):
        dae_file_path = context.scene.dae_file_path

        if not dae_file_path:
            self.report({'ERROR'}, "DAE file path is required.")
            return {'CANCELLED'}

        # Ensure the DAE file path is absolute
        dae_file_path = ensure_absolute_path(dae_file_path)

        # Check if the DAE file exists
        if not os.path.exists(dae_file_path):
            self.report({'ERROR'}, f"DAE file does not exist: {dae_file_path}")
            return {'CANCELLED'}

        # Perform texture processing and UV reassignment
        process_and_assign_textures_with_mirroring(dae_file_path)
        return {'FINISHED'}

class ExportGLBWithWrapsOperator(bpy.types.Operator):
    """Operator to export the .glb with wrap modes"""
    bl_idname = "export.glb_with_wraps"
    bl_label = "Export .glb with Wraps"

    def execute(self, context):
        dae_file_path = context.scene.dae_file_path
        output_directory = context.scene.output_directory
        output_filename = context.scene.output_filename

        if not dae_file_path or not output_directory:
            self.report({'ERROR'}, "DAE file and output directory are required.")
            return {'CANCELLED'}

        # Ensure the dae_file_path is absolute
        dae_file_path = ensure_absolute_path(dae_file_path)
        
        # Check if the DAE file exists
        if not os.path.exists(dae_file_path):
            self.report({'ERROR'}, f"DAE file does not exist: {dae_file_path}")
            return {'CANCELLED'}

        # Ensure the output_directory is absolute
        output_directory = ensure_absolute_path(output_directory)

        # Ensure output_filename is provided
        output_filename = output_filename or "model"

        # Check if the output directory exists
        if not os.path.isdir(output_directory):
            self.report({'ERROR'}, f"Output directory does not exist: {output_directory}")
            return {'CANCELLED'}

        # Perform the export with the absolute paths
        export_glb_with_custom_wrap(output_directory, output_filename, dae_file_path)
        return {'FINISHED'}

class FixScalingOperator(bpy.types.Operator):
    """Operator to fix scaling by scaling the entire model by 0.01"""
    bl_idname = "export.fix_scaling"
    bl_label = "Fix Scaling (Scale by 0.01)"

    def execute(self, context):
        scale_scene(0.01)
        return {'FINISHED'}


def register():
    bpy.utils.register_class(ExportGLBPanel)
    bpy.utils.register_class(ExportGLBWithWrapsOperator)
    bpy.utils.register_class(FixScalingOperator)
    bpy.utils.register_class(CondenseWrapIntoTextureOperator)

    bpy.types.Scene.dae_file_path = bpy.props.StringProperty(name="DAE File Path", subtype="FILE_PATH")
    bpy.types.Scene.output_directory = bpy.props.StringProperty(name="Output Directory", subtype="DIR_PATH")
    bpy.types.Scene.output_filename = bpy.props.StringProperty(name="Output Filename", subtype="NONE")


def unregister():
    bpy.utils.unregister_class(ExportGLBPanel)
    bpy.utils.unregister_class(ExportGLBWithWrapsOperator)
    bpy.utils.unregister_class(FixScalingOperator)
    bpy.utils.unregister_class(CondenseWrapIntoTextureOperator)

    del bpy.types.Scene.dae_file_path
    del bpy.types.Scene.output_directory
    del bpy.types.Scene.output_filename


if __name__ == "__main__":
    register()
