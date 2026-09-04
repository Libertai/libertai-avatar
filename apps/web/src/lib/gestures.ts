import { VRMAnimationLoaderPlugin, createVRMAnimationClip, type VRMAnimation } from "@pixiv/three-vrm-animation";
import type { VRM } from "@pixiv/three-vrm";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { AnimationClip } from "three";

/**
 * Load a VRM Animation (`.vrma`) file and retarget it onto a VRM's humanoid rig.
 *
 * Args:
 *   url: Location of the `.vrma` file, including blob URLs from a file picker.
 *   vrm: The avatar the clip is retargeted onto; clips are rig-specific.
 *
 * Returns:
 *   A clip ready for an AnimationMixer, or null when the file holds no animation.
 */
export async function loadGestureClip(url: string, vrm: VRM): Promise<AnimationClip | null> {
  const loader = new GLTFLoader();
  loader.register((parser) => new VRMAnimationLoaderPlugin(parser));

  const gltf = await loader.loadAsync(url);
  const animations = gltf.userData.vrmAnimations as VRMAnimation[] | undefined;
  const animation = animations?.[0];
  if (!animation) {
    return null;
  }

  return createVRMAnimationClip(animation, vrm);
}
