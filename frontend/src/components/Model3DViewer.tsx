// 3D preview panel. (Phase 4d)
// View-only: drag to rotate, scroll/pinch to zoom. All changes go through the chat.

import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'

// Flat, faceted preview shading makes each facet one flat mirror: on a glossy part a
// whole facet facing the light turns white, which looks like a blank patch. Previews
// keep highlights soft; the final file (smooth shading, in Blender) keeps the real gloss.
const PREVIEW_MIN_ROUGHNESS = 0.5
import { API_BASE, type Model3DData } from '../ws'

interface Viewer {
  scene: THREE.Scene
  camera: THREE.PerspectiveCamera
  controls: OrbitControls
  holder: THREE.Group // the object, floating
  radius: number // size of the current object, for framing and floating
  framed: boolean
}

function disposeObject(root: THREE.Object3D) {
  root.traverse((node) => {
    const mesh = node as THREE.Mesh
    if (mesh.isMesh) {
      mesh.geometry.dispose()
      const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
      materials.forEach((m) => m.dispose())
    }
  })
}

function frame(v: Viewer) {
  const d = v.radius * 3.2
  v.camera.position.set(d * 0.8, d * 0.55, d)
  v.camera.near = v.radius / 100
  v.camera.far = v.radius * 100
  v.camera.updateProjectionMatrix()
  v.controls.target.set(0, 0, 0)
  v.controls.minDistance = v.radius * 0.6
  v.controls.maxDistance = v.radius * 12
  v.controls.update()
}

export default function Model3DViewer({ data }: { data: Model3DData }) {
  const mountRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<Viewer | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // The version you clicked. It only counts until a new version arrives.
  const [pick, setPick] = useState<{ version: number; key: string } | null>(null)
  const key = `${data.current}/${data.versions.length}`
  const viewing = pick?.key === key ? pick.version : data.current
  const version = data.versions.find((v) => v.version === viewing) ?? data.versions[data.versions.length - 1]
  const fromLibrary = version.source === 'library' // a finished model: shown as it is, not as a preview

  // Set up the 3D view once.
  useEffect(() => {
    const mount = mountRef.current!
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.outputColorSpace = THREE.SRGBColorSpace
    mount.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    // A soft studio "room" for glossy and metal parts to reflect (without it, metal looks black).
    const pmrem = new THREE.PMREMGenerator(renderer)
    const environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture
    scene.environment = environment
    scene.environmentIntensity = 0.6 // enough to show gloss and metal, without washing out dark colors
    // Neutral white lights on top, so colors look like themselves.
    scene.add(new THREE.HemisphereLight(0xffffff, 0x30343c, 0.6))
    const key = new THREE.DirectionalLight(0xffffff, 1.3)
    key.position.set(3, 5, 4)
    scene.add(key)
    const rim = new THREE.DirectionalLight(0xffffff, 0.4)
    rim.position.set(-4, 2, -3)
    scene.add(rim)

    const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 1000)
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enablePan = false // view only: rotate and zoom
    controls.enableDamping = true
    const holder = new THREE.Group()
    scene.add(holder)
    const viewer: Viewer = { scene, camera, controls, holder, radius: 1, framed: false }
    viewerRef.current = viewer

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = mount
      if (!w || !h) return
      renderer.setSize(w, h)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
    }
    const observer = new ResizeObserver(resize)
    observer.observe(mount)
    resize()

    const clock = new THREE.Clock()
    renderer.setAnimationLoop(() => {
      holder.position.y = Math.sin(clock.getElapsedTime() * 1.2) * viewer.radius * 0.03 // floating in space
      controls.update()
      renderer.render(scene, camera)
    })

    return () => {
      renderer.setAnimationLoop(null)
      observer.disconnect()
      controls.dispose()
      disposeObject(holder)
      environment.dispose()
      pmrem.dispose()
      renderer.dispose()
      mount.removeChild(renderer.domElement)
      viewerRef.current = null
    }
  }, [])

  // Load the version being viewed.
  const url = API_BASE + version.preview_url
  useEffect(() => {
    const viewer = viewerRef.current
    if (!viewer) return
    let cancelled = false
    setLoading(true)
    setError(null)
    new GLTFLoader().load(
      url,
      (gltf) => {
        if (cancelled) return disposeObject(gltf.scene)
        const model = gltf.scene
        // Preview look: flat, faceted shading with soft highlights. Library models are finished: left as they are.
        if (!fromLibrary) {
          model.traverse((node) => {
            const mesh = node as THREE.Mesh
            if (mesh.isMesh) {
              const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
              materials.forEach((m) => {
                const standard = m as THREE.MeshStandardMaterial
                standard.flatShading = true
                standard.roughness = Math.max(standard.roughness, PREVIEW_MIN_ROUGHNESS)
                m.needsUpdate = true
              })
            }
          })
        }
        // Center it, so it rotates around its middle.
        const box = new THREE.Box3().setFromObject(model)
        model.position.sub(box.getCenter(new THREE.Vector3()))
        disposeObject(viewer.holder)
        viewer.holder.clear()
        viewer.holder.add(model)
        viewer.radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.01)
        if (!viewer.framed) {
          frame(viewer)
          viewer.framed = true
        }
        setLoading(false)
      },
      undefined,
      () => {
        if (!cancelled) {
          setError('Could not load this preview.')
          setLoading(false)
        }
      },
    )
    return () => {
      cancelled = true
    }
  }, [url, fromLibrary])

  const [w, h, d] = version.size
  const exports = data.exports.slice().reverse()
  return (
    <div className="model-viewer">
      <div className="model-stage" ref={mountRef}>
        <div className="stage-badge">
          {fromLibrary ? 'Library model' : 'Preview · low detail'} · v{version.version}
          <span>
            {w} × {h} × {d} m
          </span>
        </div>
        <button
          className="model-reset"
          onClick={() => viewerRef.current && frame(viewerRef.current)}
          title="Reset the view"
        >
          Reset view
        </button>
        <div className="model-hint">Drag to rotate · scroll to zoom · changes go through the chat</div>
        {loading && <div className="model-status">Loading preview…</div>}
        {error && <div className="model-status error">{error}</div>}
      </div>

      <div className="model-bar">
        <div className="version-strip" role="list">
          {data.versions.map((v) => (
            <button
              key={v.version}
              role="listitem"
              className={`version-chip${v.version === version.version ? ' viewing' : ''}`}
              onClick={() => setPick({ version: v.version, key })}
              title={v.note}
            >
              v{v.version}
            </button>
          ))}
        </div>
        <span className="model-note">{version.note}</span>
      </div>

      {exports.length > 0 && (
        <div className="model-exports">
          <span>Final files:</span>
          {exports.map((e) => (
            <a key={e.url} className="image-download" href={`${API_BASE}${e.url}?download=1`}>
              ↓ {e.name}
            </a>
          ))}
        </div>
      )}
    </div>
  )
}
