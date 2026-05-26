import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import * as THREE from "three";

// Mechanical port of backend/static/os1-loader.js. Renders the rotating
// ribbon from the film (Siyoung Park, MIT) into a Three.js canvas.
// The imperative API (transform/untransform/setActive/reset) lets
// outside screens drive cinematic transitions.
const SIZES = {
  small:  280,
  medium: 420,
  large:  720,
} as const;

export interface OS1LoaderHandle {
  transform: (fast?: boolean) => void;
  untransform: () => void;
  setActive: (active: boolean) => void;
  reset: () => void;
}

interface OS1LoaderProps {
  size?: keyof typeof SIZES;
  startTransformed?: boolean;
  backgroundColor?: string;
}

export const OS1Loader = forwardRef<OS1LoaderHandle, OS1LoaderProps>(
  function OS1Loader(
    { size = "small", startTransformed = false, backgroundColor = "#d1684e" },
    ref,
  ) {
    const containerRef = useRef<HTMLDivElement>(null);
    const apiRef = useRef<OS1LoaderHandle | null>(null);

    useEffect(() => {
      const container = containerRef.current;
      if (!container) return;
      const pi2 = Math.PI * 2;
      const length = 30;
      const radius = 5.6;

      let toend = startTransformed;
      let animatestep = startTransformed ? 240 : 0;
      let acceleration = startTransformed ? 1 : 0;
      let stepIncrement = startTransformed ? 1.8 : 1;
      let rotatevalue = 0.035;
      let running = true;

      const normalRotate = 0.035;
      const fastRotate = 0.12;
      const transformSpeed = 1.8;
      const normalSpeed = 1;

      const camera = new THREE.PerspectiveCamera(65, 1, 1, 10000);
      camera.position.z = 150;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(backgroundColor);

      const group = new THREE.Group();
      scene.add(group);

      class CustomSinCurve extends THREE.Curve<THREE.Vector3> {
        scale: number;
        constructor(scale = 1) { super(); this.scale = scale; }
        getPoint(t: number): THREE.Vector3 {
          const x = length * Math.sin(pi2 * t);
          const y = radius * Math.cos(pi2 * 3 * t);
          let tmod = (t % 0.25) / 0.25;
          tmod = (t % 0.25) - (2 * (1 - tmod) * tmod * -0.0185 + tmod * tmod * 0.25);
          if (Math.floor(t / 0.25) === 0 || Math.floor(t / 0.25) === 2) tmod *= -1;
          const z = radius * Math.sin(pi2 * 2 * (t - tmod));
          return new THREE.Vector3(x, y, z).multiplyScalar(this.scale);
        }
      }

      const path = new CustomSinCurve(1);
      const mesh = new THREE.Mesh(
        new THREE.TubeGeometry(path, 200, 1.1, 2, true),
        new THREE.MeshBasicMaterial({ color: 0xffffff }),
      );
      group.add(mesh);

      const ringcover = new THREE.Mesh(
        new THREE.PlaneGeometry(50, 15, 1),
        new THREE.MeshBasicMaterial({
          color: backgroundColor, opacity: 0, transparent: true,
        }),
      );
      ringcover.position.x = length + 1;
      ringcover.rotation.y = Math.PI / 2;
      group.add(ringcover);

      for (let i = 0; i < 10; i++) {
        const plain = new THREE.Mesh(
          new THREE.PlaneGeometry(length * 2 + 1, radius * 3, 1),
          new THREE.MeshBasicMaterial({
            color: backgroundColor, transparent: true, opacity: 0.13,
          }),
        );
        plain.position.z = -2.5 + i * 0.5;
        group.add(plain);
      }

      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setClearColor(backgroundColor);

      const updateSize = () => {
        const s = Math.min(container.clientWidth, container.clientHeight);
        if (s > 0) renderer.setSize(s, s);
      };
      updateSize();
      container.appendChild(renderer.domElement);

      const easing = (t: number, b: number, c: number, d: number): number => {
        if ((t /= d / 2) < 1) return (c / 2) * t * t + b;
        return (c / 2) * ((t -= 2) * t * t + 2) + b;
      };

      const render = () => {
        if (toend) animatestep = Math.min(240, animatestep + stepIncrement);
        else animatestep = Math.max(0, animatestep - stepIncrement * 1.4);
        acceleration = easing(animatestep, 0, 1, 240);

        const mat = mesh.material as THREE.MeshBasicMaterial;
        const ringMat = ringcover.material as THREE.MeshBasicMaterial;

        if (acceleration > 0.35) {
          const progress = (acceleration - 0.35) / 0.65;
          group.rotation.y = -Math.PI / 2 * progress;
          group.position.z = 50 * progress;
          const fade = Math.max(0, (acceleration - 0.85) / 0.15);
          if (fade > 0) { mat.transparent = true; mat.opacity = 1 - fade; }
          ringMat.opacity = fade;
        } else {
          group.rotation.y *= 0.85;
          group.position.z *= 0.85;
          if (mat.opacity < 1) mat.opacity = Math.min(1, mat.opacity + 0.05);
          else if (mat.transparent) { mat.transparent = false; mat.needsUpdate = true; }
          if (ringMat.opacity > 0) ringMat.opacity = Math.max(0, ringMat.opacity - 0.05);
        }
        renderer.render(scene, camera);
      };

      let frameId: number;
      const animate = () => {
        if (!running) return;
        mesh.rotation.x += rotatevalue + acceleration;
        render();
        frameId = requestAnimationFrame(animate);
      };
      animate();

      apiRef.current = {
        transform(fast = true) { toend = true; stepIncrement = fast ? transformSpeed : normalSpeed; },
        untransform() { toend = false; stepIncrement = normalSpeed; },
        setActive(active) { rotatevalue = active ? fastRotate : normalRotate; },
        reset() {
          toend = false; animatestep = 0; acceleration = 0;
          group.rotation.y = 0; group.position.z = 0;
          (mesh.material as THREE.MeshBasicMaterial).opacity = 1;
          (mesh.material as THREE.MeshBasicMaterial).transparent = false;
          (mesh.material as THREE.MeshBasicMaterial).needsUpdate = true;
          (ringcover.material as THREE.MeshBasicMaterial).opacity = 0;
        },
      };

      const onResize = () => updateSize();
      window.addEventListener("resize", onResize);

      return () => {
        running = false;
        cancelAnimationFrame(frameId);
        window.removeEventListener("resize", onResize);
        renderer.dispose();
        if (container.contains(renderer.domElement)) {
          container.removeChild(renderer.domElement);
        }
        apiRef.current = null;
      };
    }, [backgroundColor, startTransformed]);

    useImperativeHandle(
      ref,
      () => ({
        transform: (fast) => apiRef.current?.transform(fast),
        untransform: () => apiRef.current?.untransform(),
        setActive: (active) => apiRef.current?.setActive(active),
        reset: () => apiRef.current?.reset(),
      }),
      [],
    );

    const px = SIZES[size];
    return (
      <div
        ref={containerRef}
        style={{ width: px, height: px, display: "block", pointerEvents: "none" }}
      />
    );
  },
);
