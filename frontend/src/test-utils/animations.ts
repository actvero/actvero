export async function waitForAnimations() {
  await Promise.all(
    document
      .getAnimations()
      .filter(
        (animation) =>
          animation.effect?.getComputedTiming().iterations !== Infinity
      )
      .map((animation) => animation.finished.catch(() => {}))
  )
}
