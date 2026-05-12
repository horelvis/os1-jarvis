/**
 * OS1 Loader — the rotating ribbon (cinta) from the film.
 *
 * Based on the original by Siyoung Park (MIT License):
 *   https://codepen.io/psyonline/pen/yayYWg
 *
 * Exports a factory that creates an animated Three.js scene in a
 * given container. Returns a control object so external code can
 * trigger the ribbon-to-disc transformation, pause rendering, etc.
 */

import * as THREE from 'three';

export function createOS1Loader(container, options = {}) {
  const {
    backgroundColor = '#d1684e',
    length = 30,
    radius = 5.6,
    startTransformed = false,
  } = options;

  const pi2 = Math.PI * 2;

  // Externally-controllable state
  let toend = startTransformed;
  let animatestep = startTransformed ? 240 : 0;
  let acceleration = startTransformed ? 1 : 0;
  let stepIncrement = startTransformed ? 1.8 : 1;
  let rotatevalue = 0.035;
  let running = true;
  let visible = true;

  const normalRotate = 0.035;
  const fastRotate = 0.12;
  const transformSpeed = 1.8;
  const normalSpeed = 1;

  // Scene
  const camera = new THREE.PerspectiveCamera(65, 1, 1, 10000);
  camera.position.z = 150;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(backgroundColor);

  const group = new THREE.Group();
  scene.add(group);

  // Parametric curve — the original "Her" ribbon shape
  class CustomSinCurve extends THREE.Curve {
    constructor(scale = 1) {
      super();
      this.scale = scale;
    }
    getPoint(t) {
      const x = length * Math.sin(pi2 * t);
      const y = radius * Math.cos(pi2 * 3 * t);
      let z, tmod;
      tmod = (t % 0.25) / 0.25;
      tmod = (t % 0.25) - (2 * (1 - tmod) * tmod * -0.0185 + tmod * tmod * 0.25);
      if (Math.floor(t / 0.25) === 0 || Math.floor(t / 0.25) === 2) {
        tmod *= -1;
      }
      z = radius * Math.sin(pi2 * 2 * (t - tmod));
      return new THREE.Vector3(x, y, z).multiplyScalar(this.scale);
    }
  }

  const path = new CustomSinCurve(1);
  const mesh = new THREE.Mesh(
    new THREE.TubeGeometry(path, 200, 1.1, 2, true),
    new THREE.MeshBasicMaterial({ color: 0xffffff })
  );
  group.add(mesh);

  const ringcover = new THREE.Mesh(
    new THREE.PlaneGeometry(50, 15, 1),
    new THREE.MeshBasicMaterial({ color: backgroundColor, opacity: 0, transparent: true })
  );
  ringcover.position.x = length + 1;
  ringcover.rotation.y = Math.PI / 2;
  group.add(ringcover);

  // Fog planes to soften the back of the ribbon
  for (let i = 0; i < 10; i++) {
    const plain = new THREE.Mesh(
      new THREE.PlaneGeometry(length * 2 + 1, radius * 3, 1),
      new THREE.MeshBasicMaterial({ color: backgroundColor, transparent: true, opacity: 0.13 })
    );
    plain.position.z = -2.5 + i * 0.5;
    group.add(plain);
  }

  // Renderer
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(backgroundColor);

  function updateSize() {
    const size = Math.min(container.clientWidth, container.clientHeight);
    if (size > 0) renderer.setSize(size, size);
  }
  updateSize();
  container.appendChild(renderer.domElement);

  function easing(t, b, c, d) {
    if ((t /= d / 2) < 1) return (c / 2) * t * t + b;
    return (c / 2) * ((t -= 2) * t * t + 2) + b;
  }

  function render() {
    if (toend) {
      animatestep = Math.min(240, animatestep + stepIncrement);
    } else {
      animatestep = Math.max(0, animatestep - stepIncrement * 1.4);
    }
    acceleration = easing(animatestep, 0, 1, 240);

    if (acceleration > 0.35) {
      const progress = (acceleration - 0.35) / 0.65;
      group.rotation.y = -Math.PI / 2 * progress;
      group.position.z = 50 * progress;
      const progressOpacity = Math.max(0, (acceleration - 0.85) / 0.15);
      if (progressOpacity > 0) {
        mesh.material.transparent = true;
        mesh.material.opacity = 1 - progressOpacity;
      }
      ringcover.material.opacity = progressOpacity;
    } else {
      group.rotation.y *= 0.85;
      group.position.z *= 0.85;
      if (mesh.material.opacity < 1) {
        mesh.material.opacity = Math.min(1, mesh.material.opacity + 0.05);
      } else if (mesh.material.transparent) {
        mesh.material.transparent = false;
        mesh.material.needsUpdate = true;
      }
      if (ringcover.material.opacity > 0) {
        ringcover.material.opacity = Math.max(0, ringcover.material.opacity - 0.05);
      }
    }

    renderer.render(scene, camera);
  }

  let frameId;
  function animate() {
    if (!running) return;
    if (visible) {
      mesh.rotation.x += rotatevalue + acceleration;
      render();
    }
    frameId = requestAnimationFrame(animate);
  }
  animate();

  return {
    transform(fast = true) {
      toend = true;
      stepIncrement = fast ? transformSpeed : normalSpeed;
    },
    untransform() {
      toend = false;
      stepIncrement = normalSpeed;
    },
    setActive(active) {
      rotatevalue = active ? fastRotate : normalRotate;
    },
    setVisible(v) {
      visible = v;
    },
    reset() {
      toend = false;
      animatestep = 0;
      acceleration = 0;
      group.rotation.y = 0;
      group.position.z = 0;
      mesh.material.opacity = 1;
      mesh.material.transparent = false;
      mesh.material.needsUpdate = true;
      ringcover.material.opacity = 0;
    },
    destroy() {
      running = false;
      if (frameId) cancelAnimationFrame(frameId);
      renderer.dispose();
      container.innerHTML = '';
    },
    resize: updateSize,
  };
}
