// Readable names for models and tools, shared by the chat and the HUD panels.

import type { ActiveTool } from './ws'

/** "claude-haiku-4-5-20251001" -> "haiku" */
export function modelFamily(modelId: string): 'haiku' | 'sonnet' | 'opus' | 'other' {
  const id = modelId.toLowerCase()
  if (id.includes('haiku')) return 'haiku'
  if (id.includes('sonnet')) return 'sonnet'
  if (id.includes('opus')) return 'opus'
  return 'other'
}

export function toolLabel({ name, detail, label }: ActiveTool): string {
  switch (name) {
    case 'ask_expert':
      return 'Consulting Opus (expert)…'
    case 'WebSearch':
      return detail ? `Searching the web for “${detail}”…` : 'Searching the web…'
    case 'WebFetch':
      return detail ? `Reading ${detail}…` : 'Reading a web page…'
    case 'ToolSearch':
      return 'Looking for the right tool…'
    case 'image_search':
      return 'Finding a photo…'
    case 'image_edit':
      return 'Editing the image…'
    case 'generate_image':
      return 'Painting the image…'
    case 'image_ai_edit':
      return 'Changing the image with AI…'
    case 'image_undo':
    case 'revert_3d':
      return 'Going back a version…'
    case 'search_3d_library':
      return 'Looking in the 3D library…'
    case 'show_from_3d_library':
      return 'Opening the 3D model…'
    case 'preview_3d':
      return 'Building the 3D preview…'
    case 'get_3d_spec':
      return 'Reading the 3D model…'
    case 'generate_video':
      return 'Starting the video…'
    case 'export_3d':
      return 'Building the final 3D file in Blender…'
    default:
      return `${label || name}…`
  }
}

/** "groq/openai/gpt-oss-120b" -> { provider: "Groq", model: "gpt-oss-120b" } */
export function gatewayModelName(id: string): { provider: string; model: string } {
  const [provider, ...rest] = id.split('/')
  const model = rest.length ? rest[rest.length - 1] : provider
  return { provider: provider.charAt(0).toUpperCase() + provider.slice(1), model }
}
