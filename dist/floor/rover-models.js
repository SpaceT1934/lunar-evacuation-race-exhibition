import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

export async function loadRoverViews() {
  const loader = new GLTFLoader();
  const rovers = await Promise.all(
    ['blue', 'gold'].map(async (color) => {
      const url = new URL(`../assets/models/science-rover-${color}.glb`, import.meta.url);
      return (await loader.loadAsync(url.href)).scene;
    }),
  );
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  const size = 256;
  renderer.setSize(size, size, false);
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-0.64, 0.64, 0.64, -0.64, 0.1, 10);
  camera.position.set(0, 3, 1.3);
  camera.lookAt(0, 0, 0);
  scene.add(new THREE.HemisphereLight(0xf5f8ff, 0x555264, 2.2));
  const key = new THREE.DirectionalLight(0xffedd4, 2.1);
  key.position.set(-2, 4, 2);
  scene.add(key);

  try {
    return rovers.map((rover) => {
      const bounds = new THREE.Box3().setFromObject(rover);
      const center = bounds.getCenter(new THREE.Vector3());
      const dimensions = bounds.getSize(new THREE.Vector3());
      const model = new THREE.Group();
      rover.position.sub(center);
      model.add(rover);
      model.scale.setScalar(1 / Math.max(dimensions.x, dimensions.z));
      scene.add(model);
      renderer.render(scene, camera);

      const view = document.createElement('canvas');
      view.width = view.height = size;
      view.getContext('2d').drawImage(renderer.domElement, 0, 0);
      scene.remove(model);
      return view;
    });
  } finally {
    renderer.dispose();
    renderer.forceContextLoss();
  }
}
