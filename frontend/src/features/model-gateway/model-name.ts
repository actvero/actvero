// Mirrors the publication identifier contract; aliases keep interior ASCII spaces.
export function supportsMemberAccess(name: string) {
  return (
    name.length <= 128 &&
    name === name.trim() &&
    /^[A-Za-z0-9](?:[A-Za-z0-9._:/@+ -]*[A-Za-z0-9._:/@+-])?$/.test(name)
  )
}
