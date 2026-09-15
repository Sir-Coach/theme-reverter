import os
import bpy
import zipfile
import xml.etree.ElementTree as ET


# XML HELPERS

def find_element(root, path):
    """Find an element by dotted path. `root` is the <bpy> element."""
    parts = path.split(".")
    if parts and parts[0] == root.tag:
        parts = parts[1:]
    elem = root
    for part in parts:
        found = None
        for child in elem:
            if child.tag == part:
                found = child
                break
        if found is None:
            return None
        elem = found
    return elem


def find_or_create(root, path):
    """Find or create nested elements along a dotted path."""
    parts = path.split(".")
    if parts and parts[0] == root.tag:
        parts = parts[1:]
    elem = root
    for part in parts:
        child = elem.find(part)
        if child is None:
            child = ET.SubElement(elem, part)
        elem = child
    return elem


def remove_element(root, path):
    """Remove an element at a dotted path."""
    parts = path.split(".")
    if parts and parts[0] == root.tag:
        parts = parts[1:]
    if not parts:
        return False
    parent = root
    for part in parts[:-1]:
        parent = parent.find(part)
        if parent is None:
            return False
    tag = parts[-1]
    for child in list(parent):
        if child.tag == tag:
            parent.remove(child)
            return True
    return False


def flat_attrs(root):
    """Return {dotted_path.attr: value} for every attribute in the tree."""
    result = {}

    def walk(elem, path):
        current = f"{path}.{elem.tag}" if path else elem.tag
        for attr, value in elem.attrib.items():
            result[f"{current}.{attr}"] = value
        for child in elem:
            walk(child, current)

    walk(root, "")
    return result


def drop_attrs_by_tag(root, tag_to_attrs):
    """Recursively drop attributes from every element whose tag is a key."""
    def walk(elem):
        if elem.tag in tag_to_attrs:
            for a in tag_to_attrs[elem.tag]:
                elem.attrib.pop(a, None)
        for child in elem:
            walk(child)
    walk(root)


def set_attr(root, path, attr, value):
    """Set attribute on an element; creates the element if needed."""
    if value is None:
        return
    elem = find_or_create(root, path)
    elem.set(attr, str(value))


# ZIP / FILE HELPERS

def _load_source_tree(src_path):
    """Load a theme XML tree from a .xml or .zip file.

    Returns (tree, xml_filename). Raises ValueError on failure.
    For .zip files, the shallowest .xml member is chosen — this is almost
    always the theme file, with the manifest.toml sitting next to it.
    """
    lower = src_path.lower()

    if lower.endswith('.zip'):
        try:
            with zipfile.ZipFile(src_path, 'r') as zf:
                xml_members = [
                    n for n in zf.namelist()
                    if n.lower().endswith('.xml') and not n.endswith('/')
                ]
                if not xml_members:
                    raise ValueError("No .xml file found inside the zip archive.")
                # Prefer the shallowest path, then the shortest name.
                xml_members.sort(key=lambda n: (n.count('/'), len(n), n))
                target = xml_members[0]
                with zf.open(target) as fp:
                    tree = ET.parse(fp)
                return tree, os.path.basename(target)
        except zipfile.BadZipFile as e:
            raise ValueError(f"Not a valid zip file: {e}")
        except ET.ParseError as e:
            raise ValueError(f"Failed to parse XML inside zip: {e}")

    if lower.endswith('.xml'):
        try:
            tree = ET.parse(src_path)
        except ET.ParseError as e:
            raise ValueError(f"Failed to parse XML: {e}")
        return tree, os.path.basename(src_path)

    raise ValueError("Source must be a .xml or .zip file.")


def _resolve_output_path(prefs, src_path, xml_name):
    """Return a final .xml output path.

    - Empty prefs.output_filepath  -> auto-name next to the source
    - A directory                  -> auto-name inside that directory
    - A path without .xml          -> append .xml
    """
    base = os.path.splitext(xml_name)[0]
    auto_name = f"{base}_reverted_45.xml"

    out = (prefs.output_filepath or "").strip()
    if not out:
        folder = os.path.dirname(src_path) or os.getcwd()
        return os.path.join(folder, auto_name)

    # User picked a folder in the file browser.
    if os.path.isdir(out):
        return os.path.join(out, auto_name)

    # Ensure a .xml extension.
    if not out.lower().endswith('.xml'):
        out += '.xml'
    return out


# MAPPINGS

# All paths are relative to <Theme> (e.g. "user_interface.ThemeUserInterface").

# DROP (5.0-only)

# Attributes dropped from specific elements
DROP_ATTRS = {
    "user_interface.ThemeUserInterface": [
        "link",
        "panel_header", "panel_title", "panel_text",
        "panel_back", "panel_sub_back",
        "panel_outline", "panel_active",
        "axis_w",
    ],
    "properties.ThemeProperties": ["active_modifier"],
    "preferences.ThemePreferences": ["match"],
    "node_editor.ThemeNodeEditor": ["node_outline", "closure_zone"],
    "view_3d.ThemeView3D": ["grid_major", "grid_axis_brightness", "gp_wire_edit"],
    "dopesheet_editor.ThemeDopeSheet": [
        "anim_interpolation_constant", "anim_interpolation_other",
    ],
}

# Attributes dropped from every element with the given tag
DROP_ATTRS_BY_TAG = {
    "ThemeWidgetColors": ["outline_sel"],
}

# Elements dropped entirely (relative to <Theme>)
DROP_ELEMENTS = [
    "user_interface.ThemeUserInterface.wcol_curve",
    "regions",
    "common",
]


# RENAMES

# (src_attr, dst_attr) inside a given element path
RENAMES = {
    "view_3d.ThemeView3D": [
        ("bevel", "edge_bevel"),
        ("seam", "edge_seam"),
        ("sharp", "edge_sharp"),
        ("crease", "edge_crease"),
        ("freestyle", "freestyle_face_mark"),
    ],
    "dopesheet_editor.ThemeDopeSheet": [
        ("anim_interpolation_linear", "interpolation_line"),
    ],
}


# EDITOR GROUPS

# (editor_path, editor_tag, space_tag) — used for panel colors + sidebars
EDITOR_SPACES = [
    ("view_3d",            "ThemeView3D",         "ThemeSpaceGradient"),
    ("graph_editor",       "ThemeGraphEditor",    "ThemeSpaceGeneric"),
    ("file_browser",       "ThemeFileBrowser",    "ThemeSpaceGeneric"),
    ("nla_editor",         "ThemeNLAEditor",      "ThemeSpaceGeneric"),
    ("dopesheet_editor",   "ThemeDopeSheet",      "ThemeSpaceGeneric"),
    ("image_editor",       "ThemeImageEditor",    "ThemeSpaceGeneric"),
    ("sequence_editor",    "ThemeSequenceEditor", "ThemeSpaceGeneric"),
    ("properties",         "ThemeProperties",     "ThemeSpaceGeneric"),
    ("text_editor",        "ThemeTextEditor",     "ThemeSpaceGeneric"),
    ("node_editor",        "ThemeNodeEditor",     "ThemeSpaceGeneric"),
    ("outliner",           "ThemeOutliner",       "ThemeSpaceGeneric"),
    ("info",               "ThemeInfo",           "ThemeSpaceGeneric"),
    ("preferences",        "ThemePreferences",    "ThemeSpaceGeneric"),
    ("console",            "ThemeConsole",        "ThemeSpaceGeneric"),
    ("clip_editor",        "ThemeClipEditor",     "ThemeSpaceGeneric"),
    ("topbar",             "ThemeTopBar",         "ThemeSpaceGeneric"),
    ("statusbar",          "ThemeStatusBar",      "ThemeSpaceGeneric"),
    ("spreadsheet",        "ThemeSpreadsheet",    "ThemeSpaceGeneric"),
]

EDITORS_WITH_ASSET_SHELF = [
    "view_3d.ThemeView3D",
    "image_editor.ThemeImageEditor",
]

EDITORS_WITH_SPACE_LIST = [
    "graph_editor.ThemeGraphEditor",
    "nla_editor.ThemeNLAEditor",
    "dopesheet_editor.ThemeDopeSheet",
    "node_editor.ThemeNodeEditor",
    "clip_editor.ThemeClipEditor",
    "spreadsheet.ThemeSpreadsheet",
    "sequence_editor.ThemeSequenceEditor",
]

EDITORS_WITH_SCRUB = [
    "graph_editor.ThemeGraphEditor",
    "nla_editor.ThemeNLAEditor",
    "dopesheet_editor.ThemeDopeSheet",
    "sequence_editor.ThemeSequenceEditor",
    "clip_editor.ThemeClipEditor",
]

EDITORS_WITH_PLAYHEAD = [
    "graph_editor.ThemeGraphEditor",
    "nla_editor.ThemeNLAEditor",
    "dopesheet_editor.ThemeDopeSheet",
    "sequence_editor.ThemeSequenceEditor",
    "clip_editor.ThemeClipEditor",
    "image_editor.ThemeImageEditor",
]

EDITORS_WITH_CHANNELS = [
    "graph_editor.ThemeGraphEditor",
    "nla_editor.ThemeNLAEditor",
    "dopesheet_editor.ThemeDopeSheet",
]

EDITORS_WITH_CHANNEL_GROUP = [
    "graph_editor.ThemeGraphEditor",
    "dopesheet_editor.ThemeDopeSheet",
]

EDITORS_WITH_KEYFRAMES = [
    "dopesheet_editor.ThemeDopeSheet",
    "sequence_editor.ThemeSequenceEditor",
]

EDITORS_WITH_HANDLES = [
    "graph_editor.ThemeGraphEditor",
    "image_editor.ThemeImageEditor",
    "clip_editor.ThemeClipEditor",
]

# common.anim.<src> -> 4.5 attr name
KEYFRAME_MAP = [
    ("keyframe",                      "keyframe"),
    ("keyframe_selected",             "keyframe_selected"),
    ("keyframe_breakdown",            "keyframe_breakdown"),
    ("keyframe_breakdown_selected",   "keyframe_breakdown_selected"),
    ("keyframe_extreme",              "keyframe_extreme"),
    ("keyframe_extreme_selected",     "keyframe_extreme_selected"),
    ("keyframe_jitter",               "keyframe_jitter"),
    ("keyframe_jitter_selected",      "keyframe_jitter_selected"),
    ("keyframe_moving_hold",          "keyframe_movehold"),
    ("keyframe_moving_hold_selected", "keyframe_movehold_selected"),
    ("keyframe_generated",            "keyframe_generated"),
    ("keyframe_generated_selected",   "keyframe_generated_selected"),
]

CURVE_MAP = [
    "handle_free", "handle_sel_free",
    "handle_auto", "handle_sel_auto",
    "handle_vect", "handle_sel_vect",
    "handle_align", "handle_sel_align",
    "handle_auto_clamped", "handle_sel_auto_clamped",
    "handle_vertex", "handle_vertex_select", "handle_vertex_size",
]


# TRANSFORM

def _fanout(root, flat):
    """Push 5.0 shared values into every 4.5 per-editor slot."""

    # 1. Panel colors: user_interface.panel_*  ->  every space's <panelcolors>
    ui = "bpy.Theme.user_interface.ThemeUserInterface"
    header   = flat.get(f"{ui}.panel_header")
    back     = flat.get(f"{ui}.panel_back")
    sub_back = flat.get(f"{ui}.panel_sub_back")

    if header or back or sub_back:
        for ed, ed_tag, space_tag in EDITOR_SPACES:
            pc = f"bpy.Theme.{ed}.{ed_tag}.space.{space_tag}.panelcolors.ThemePanelColors"
            if header:   set_attr(root, pc, "header",   header)
            if back:     set_attr(root, pc, "back",     back)
            if sub_back: set_attr(root, pc, "sub_back", sub_back)

    # 2. Sidebars: regions.sidebars.*  ->  every space's button / tab_back
    side = "bpy.Theme.regions.ThemeRegions.sidebars.ThemeRegionsSidebars"
    sb_back = flat.get(f"{side}.back")
    sb_tab  = flat.get(f"{side}.tab_back")
    if sb_back or sb_tab:
        for ed, ed_tag, space_tag in EDITOR_SPACES:
            sp = f"bpy.Theme.{ed}.{ed_tag}.space.{space_tag}"
            if sb_back: set_attr(root, sp, "button",   sb_back)
            if sb_tab:  set_attr(root, sp, "tab_back", sb_tab)

    # 3. Asset shelf
    asrc = "bpy.Theme.regions.ThemeRegions.asset_shelf.ThemeRegionsAssetShelf"
    as_back   = flat.get(f"{asrc}.back")
    as_header = flat.get(f"{asrc}.header_back")
    if as_back or as_header:
        for ed in EDITORS_WITH_ASSET_SHELF:
            ashelf = f"bpy.Theme.{ed}.asset_shelf.ThemeAssetShelf"
            if as_header: set_attr(root, ashelf, "header_back", as_header)
            if as_back:   set_attr(root, ashelf, "back",        as_back)

    # 4. Channels -> every <space_list>
    ch = "bpy.Theme.regions.ThemeRegions.channels.ThemeRegionsChannels"
    ch_back = flat.get(f"{ch}.back")
    ch_text = flat.get(f"{ch}.text")
    ch_hi   = flat.get(f"{ch}.text_selected")
    if ch_back or ch_text or ch_hi:
        for ed in EDITORS_WITH_SPACE_LIST:
            sl = f"bpy.Theme.{ed}.space_list.ThemeSpaceListGeneric"
            if ch_back: set_attr(root, sl, "list",         ch_back)
            if ch_text: set_attr(root, sl, "list_text",    ch_text)
            if ch_hi:   set_attr(root, sl, "list_text_hi", ch_hi)

    # 5. Scrubbing
    sc = "bpy.Theme.regions.ThemeRegions.scrubbing.ThemeRegionsScrubbing"
    sc_back   = flat.get(f"{sc}.back")
    sc_mark   = flat.get(f"{sc}.time_marker")
    sc_mark_s = flat.get(f"{sc}.time_marker_selected")
    if sc_back or sc_mark or sc_mark_s:
        for ed in EDITORS_WITH_SCRUB:
            ed_path = f"bpy.Theme.{ed}"
            if sc_back:   set_attr(root, ed_path, "time_scrub_background",     sc_back)
            if sc_mark:   set_attr(root, ed_path, "time_marker_line",          sc_mark)
            if sc_mark_s: set_attr(root, ed_path, "time_marker_line_selected", sc_mark_s)

    # 6. Playhead / preview range
    anim = "bpy.Theme.common.ThemeCommon.anim.ThemeCommonAnim"
    playhead = flat.get(f"{anim}.playhead")
    preview  = flat.get(f"{anim}.preview_range")
    if playhead or preview:
        for ed in EDITORS_WITH_PLAYHEAD:
            ed_path = f"bpy.Theme.{ed}"
            if playhead: set_attr(root, ed_path, "frame_current", playhead)
            if preview:  set_attr(root, ed_path, "preview_range", preview)

    # 7. Animation channels / groups
    ch_val     = flat.get(f"{anim}.channels")
    ch_sub     = flat.get(f"{anim}.channels_sub")
    ch_grp     = flat.get(f"{anim}.channel_group")
    ch_grp_act = flat.get(f"{anim}.channel_group_active")
    ch_sel     = flat.get(f"{anim}.channel_selected")
    chan       = flat.get(f"{anim}.channel")

    for ed in EDITORS_WITH_CHANNELS:
        ed_path = f"bpy.Theme.{ed}"
        if ch_val: set_attr(root, ed_path, "dopesheet_channel",    ch_val)
        if ch_sub: set_attr(root, ed_path, "dopesheet_subchannel", ch_sub)

    for ed in EDITORS_WITH_CHANNEL_GROUP:
        ed_path = f"bpy.Theme.{ed}"
        if ch_grp:     set_attr(root, ed_path, "channel_group",         ch_grp)
        if ch_grp_act: set_attr(root, ed_path, "active_channels_group", ch_grp_act)

    if chan:
        set_attr(root, "bpy.Theme.graph_editor.ThemeGraphEditor", "channels_region", chan)
        set_attr(root, "bpy.Theme.dopesheet_editor.ThemeDopeSheet", "channels", chan)

    if ch_sel:
        set_attr(root, "bpy.Theme.dopesheet_editor.ThemeDopeSheet", "channels_selected", ch_sel)

    # 8. Keyframe colors -> dopesheet + sequence
    for ed in EDITORS_WITH_KEYFRAMES:
        ed_path = f"bpy.Theme.{ed}"
        for src, dst in KEYFRAME_MAP:
            val = flat.get(f"{anim}.{src}")
            if val: set_attr(root, ed_path, dst, val)

    # long_key is dopesheet only
    lk  = flat.get(f"{anim}.long_key")
    lks = flat.get(f"{anim}.long_key_selected")
    if lk:  set_attr(root, "bpy.Theme.dopesheet_editor.ThemeDopeSheet", "long_key",          lk)
    if lks: set_attr(root, "bpy.Theme.dopesheet_editor.ThemeDopeSheet", "long_key_selected", lks)

    # 9. Curve handles -> graph, image, clip
    curves = "bpy.Theme.common.ThemeCommon.curves.ThemeCommonCurves"
    for ed in EDITORS_WITH_HANDLES:
        ed_path = f"bpy.Theme.{ed}"
        for attr in CURVE_MAP:
            val = flat.get(f"{curves}.{attr}")
            if val: set_attr(root, ed_path, attr, val)


def transform(root):
    """In-place 5.0 XML -> 4.5 XML transform."""
    flat = flat_attrs(root)

    # 1. Fan out shared 5.0 sections into per-editor 4.5 slots
    _fanout(root, flat)

    # 2. In-place renames
    for path, renames in RENAMES.items():
        elem = find_element(root, f"bpy.Theme.{path}")
        if elem is None:
            continue
        for src, dst in renames:
            if src in elem.attrib:
                elem.set(dst, elem.attrib[src])
                del elem.attrib[src]

    # 3. Drop 5.0-only attributes from specific elements
    for path, attrs in DROP_ATTRS.items():
        elem = find_element(root, f"bpy.Theme.{path}")
        if elem is None:
            continue
        for a in attrs:
            elem.attrib.pop(a, None)

    # 4. Drop 5.0-only attributes from every matching tag
    drop_attrs_by_tag(root, DROP_ATTRS_BY_TAG)

    # 5. Drop 5.0-only elements
    for path in DROP_ELEMENTS:
        remove_element(root, f"bpy.Theme.{path}")


# PREFERENCES

class ThemeReverterAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    source: bpy.props.EnumProperty(
        name = "Theme File Source",
        description = "Where to get the 5.0+ theme file from",
        items = [
            ('CURRENT', "Active Theme", "Revert the .XML file of the currently active theme"),
            ('FILE', "Custom File", "Revert a theme from a specified .xml or .zip file"),
        ],
        default = 'CURRENT',
    )
    filepath: bpy.props.StringProperty(
        name = "Source Theme Filepath",
        description = "Path to the 5.0+ theme file (.xml or .zip)",
        subtype = 'FILE_PATH',
        default = "",
    )
    output_filepath: bpy.props.StringProperty(
        name = "Output Filepath",
        description = "Where to write the reverted 4.5 .XML file. Leave empty to place it next to the source. ",
        subtype = 'FILE_PATH',
        default = "",
    )
    install_after_revert: bpy.props.BoolProperty(
        name = "Install After Revert",
        description = "Load the reverted theme into Blender once written",
        default = True,
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column()
        row = col.row()
        row.prop(self, "source", expand=True)
        if self.source == 'FILE':
            col.prop(self, "filepath")

        layout.separator()
        col = layout.column()
        col.prop(self, "output_filepath")
        col.prop(self, "install_after_revert")

        layout.separator()
        box = layout.box()
        col = box.column()
        col.alignment = 'CENTER'
        col.label(text="Reverts a 5.0+ theme back to the 4.5 LTS format.", icon='INFO')
        col.label(text="Accepts .xml theme files or .zip theme packages.", icon='INFO')

        layout.separator()
        layout.operator("preferences.theme_revert_45")


# OPERATOR

class PREFERENCES_OT_theme_revert(bpy.types.Operator):
    bl_idname = "preferences.theme_revert_45"
    bl_label = "Revert Theme to 4.5"
    bl_description = "Revert a Blender 5.0+ theme (.xml or .zip) back to 4.5 LTS format"
    bl_options = {'UNDO'}

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences

        # 1. Resolve source path.
        if prefs.source == 'CURRENT':
            theme = context.preferences.themes[0]
            src_path = theme.filepath
        else:
            src_path = prefs.filepath

        if not src_path:
            self.report({'ERROR'}, "No source theme file specified.")
            return {'CANCELLED'}
        if not os.path.exists(src_path):
            self.report({'ERROR'}, f"File does not exist: {src_path}")
            return {'CANCELLED'}

        # 2. Load source (handles .xml and .zip).
        try:
            tree, xml_name = _load_source_tree(src_path)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        root = tree.getroot()

        # 3. Sanity check.
        looks_5 = (
            find_element(root, "bpy.Theme.regions") is not None
            or find_element(root, "bpy.Theme.common") is not None
        )
        if not looks_5:
            self.report({'WARNING'},
                "This file doesn't appear to be a 5.0+ theme. Continuing anyway.")

        # 4. Transform.
        try:
            transform(root)
        except Exception as e:
            self.report({'ERROR'}, f"Transform failed: {e}")
            return {'CANCELLED'}

        # 5. Resolve output path (auto-appends .xml).
        out_path = _resolve_output_path(prefs, src_path, xml_name)

        # 6. Write.
        try:
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            tree.write(out_path, encoding="utf-8", xml_declaration=False)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to write XML: {e}")
            return {'CANCELLED'}

        # 7. Optionally install.
        if prefs.install_after_revert:
            try:
                bpy.ops.preferences.theme_install(overwrite=True, filepath=out_path)
                self.report({'INFO'}, f"Reverted theme installed: {out_path}")
            except Exception as e:
                self.report({'WARNING'},
                    f"Reverted XML saved but could not be installed: {e}")
                self.report({'INFO'}, f"File: {out_path}")
        else:
            self.report({'INFO'}, f"Reverted XML saved: {out_path}")

        return {'FINISHED'}


# REGISTRATION

classes = [
    ThemeReverterAddonPreferences,
    PREFERENCES_OT_theme_revert,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)