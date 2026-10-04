// Het laatste stukje: de uitkomst van de rekenpassen op het canvas zetten.
//
// `textureLoad` en geen sampler: de werktextuur is net zo groot als het canvas,
// dus er is niets te interpoleren — en een sampler zou op de rand anders kunnen
// afronden dan de export.

@group(0) @binding(0) var beeld : texture_2d<f32>;

@vertex
fn vs(@builtin(vertex_index) i : u32) -> @builtin(position) vec4<f32> {
  var hoeken = array<vec2<f32>, 4>(
    vec2<f32>(0.0, 0.0), vec2<f32>(1.0, 0.0), vec2<f32>(0.0, 1.0), vec2<f32>(1.0, 1.0),
  );
  let uv = hoeken[i];
  return vec4<f32>(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, 0.0, 1.0);
}

@fragment
fn fs(@builtin(position) pos : vec4<f32>) -> @location(0) vec4<f32> {
  let c = textureLoad(beeld, vec2<i32>(i32(pos.x), i32(pos.y)), 0);
  return vec4<f32>(c.rgb, 1.0);
}
