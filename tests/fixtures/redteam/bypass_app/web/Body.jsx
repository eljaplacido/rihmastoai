export function Body({ body }) {
  return <div dangerouslySetInnerHTML={{ __html: body }} />; // seeded: RT-JS-DOMXSS
}
