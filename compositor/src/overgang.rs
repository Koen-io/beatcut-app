//! Overgangen in de export: dezelfde WGSL als de speler.
//!
//! De speler mengt aan het begin van blok B het doorlopende blok A erin
//! (`app/src/speler/Speler.tsx`). Hier gebeurt precies dat, op de GPU, met
//! `app/shaders/uniforms.wgsl` + `app/shaders/overgangen.wgsl` letterlijk
//! ingebakken. Het kader is de eenheid: ffmpeg heeft de blokken al op
//! canvasformaat gezet (vulmodus en Ken Burns), wat in de speler het kader doet.
//!
//! Het resultaat gaat daarna gewoon door look en afwerking, net als in de
//! speler (overgang eerst, dan kleur).

use wgpu::util::DeviceExt;

const UNIFORMS_WGSL: &str = include_str!("../../app/shaders/uniforms.wgsl");
const OVERGANGEN_WGSL: &str = include_str!("../../app/shaders/overgangen.wgsl");

/// De export-kant van `compositor.wgsl` in de speler, zonder kadering.
const EXPORT_WGSL: &str = r#"
struct BcUit {
  @builtin(position) pos : vec4<f32>,
  @location(0) uv : vec2<f32>,
}

@vertex
fn vs(@builtin(vertex_index) i : u32) -> BcUit {
  var hoeken = array<vec2<f32>, 4>(
    vec2<f32>(0.0, 0.0), vec2<f32>(1.0, 0.0), vec2<f32>(0.0, 1.0), vec2<f32>(1.0, 1.0),
  );
  let uv = hoeken[i];
  var o : BcUit;
  o.pos = vec4<f32>(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, 0.0, 1.0);
  o.uv = uv;
  return o;
}

@fragment
fn fs(o : BcUit) -> @location(0) vec4<f32> {
  let soort = i32(u.meng.y + 0.5);
  let t = u.meng.x;
  let seed = u.klok.z + u.klok.y;
  // Hier is bron-uv hetzelfde als canvas-uv: ffmpeg heeft de blokken al op
  // canvasformaat gezet, dus het kader is de eenheid en de vulmodus is "vul".
  let cuv = clamp(overgang_canvas_uv(soort, o.uv, t), vec2<f32>(0.0), vec2<f32>(1.0));
  let a = textureSampleLevel(beeldA, beeldsampler, cuv, 0.0);
  let b = textureSampleLevel(beeldB, beeldsampler, cuv, 0.0);
  let c = overgang_meng(soort, a, b, o.uv, t, seed);
  return vec4<f32>(clamp(c.rgb, vec3<f32>(0.0), vec3<f32>(1.0)), 1.0);
}
"#;

/// Eén overgang-moment: wat `Uniforms` in de speler meekrijgt.
#[derive(Clone, Copy, Debug)]
pub struct Moment {
    pub soort: u32,
    pub meng: f32,
    pub frame: u32,
    pub tijd: f32,
    pub seed: u32,
    pub verhouding: f32,
}

pub struct Menger {
    device: wgpu::Device,
    queue: wgpu::Queue,
    breedte: u32,
    hoogte: u32,
    pijp: wgpu::RenderPipeline,
    layout: wgpu::BindGroupLayout,
    sampler: wgpu::Sampler,
    a: wgpu::Texture,
    b: wgpu::Texture,
    doel: wgpu::Texture,
    uitlees: wgpu::Buffer,
    rij_bytes: u32,
}

impl Menger {
    pub fn nieuw(breedte: u32, hoogte: u32) -> Result<Self, String> {
        let (device, queue) = crate::gpu::apparaat(breedte, hoogte, "beatcut-overgang")?;
        let bron = format!("{UNIFORMS_WGSL}\n{OVERGANGEN_WGSL}\n{EXPORT_WGSL}");
        let module = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("overgangen"),
            source: wgpu::ShaderSource::Wgsl(bron.into()),
        });
        let tex = |binding: u32| wgpu::BindGroupLayoutEntry {
            binding,
            visibility: wgpu::ShaderStages::FRAGMENT,
            ty: wgpu::BindingType::Texture {
                sample_type: wgpu::TextureSampleType::Float { filterable: true },
                view_dimension: wgpu::TextureViewDimension::D2,
                multisampled: false,
            },
            count: None,
        };
        let layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("overgang"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    count: None,
                },
                tex(2),
                tex(3),
            ],
        });
        let pijplayout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[&layout],
            push_constant_ranges: &[],
        });
        let pijp = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("overgang"),
            layout: Some(&pijplayout),
            vertex: wgpu::VertexState {
                module: &module,
                entry_point: Some("vs"),
                buffers: &[],
                compilation_options: Default::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &module,
                entry_point: Some("fs"),
                targets: &[Some(wgpu::ColorTargetState {
                    format: wgpu::TextureFormat::Rgba8Unorm,
                    blend: None,
                    write_mask: wgpu::ColorWrites::ALL,
                })],
                compilation_options: Default::default(),
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleStrip,
                ..Default::default()
            },
            depth_stencil: None,
            multisample: Default::default(),
            multiview: None,
            cache: None,
        });
        // Zelfde sampler als de speler (`tekenen.ts`): lineair, randen geklemd.
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });
        let maak = |gebruik: wgpu::TextureUsages| {
            device.create_texture(&wgpu::TextureDescriptor {
                label: None,
                size: wgpu::Extent3d { width: breedte, height: hoogte, depth_or_array_layers: 1 },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: wgpu::TextureFormat::Rgba8Unorm,
                usage: gebruik,
                view_formats: &[],
            })
        };
        let invoer = wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST;
        let a = maak(invoer);
        let b = maak(invoer);
        let doel = maak(wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC);
        let rij_bytes = (breedte * 4).div_ceil(256) * 256;
        let uitlees = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("overgang-uitlees"),
            size: rij_bytes as u64 * hoogte as u64,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        Ok(Self { device, queue, breedte, hoogte, pijp, layout, sampler, a, b, doel, uitlees, rij_bytes })
    }

    fn schrijf(&self, tex: &wgpu::Texture, rgba: &[u8]) {
        self.queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: tex,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            rgba,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(self.breedte * 4),
                rows_per_image: Some(self.hoogte),
            },
            wgpu::Extent3d { width: self.breedte, height: self.hoogte, depth_or_array_layers: 1 },
        );
    }

    /// A (uitgaand) en B (inkomend) gemengd, als RGBA8.
    pub fn meng(&mut self, a: &[u8], b: &[u8], m: Moment) -> Result<Vec<u8>, String> {
        self.schrijf(&self.a, a);
        self.schrijf(&self.b, b);
        // `struct Uniforms` uit uniforms.wgsl: negen vec4's.
        let mut u = [0f32; 36];
        // bronA, bronB, pasA, pasB: schaal 1, verschuiving 0 — de eenheid.
        for basis in [0usize, 4, 8, 12] {
            u[basis] = 1.0;
            u[basis + 1] = 1.0;
        }
        u[16] = m.meng.clamp(0.0, 1.0);
        u[17] = m.soort as f32;
        u[20] = m.tijd;
        u[21] = m.frame as f32;
        u[22] = m.seed as f32;
        u[23] = m.verhouding;
        u[24] = 1.0;
        let uni = self.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: None,
            contents: bytemuck::cast_slice(&u),
            usage: wgpu::BufferUsages::UNIFORM,
        });
        let va = self.a.create_view(&Default::default());
        let vb = self.b.create_view(&Default::default());
        let vd = self.doel.create_view(&Default::default());
        let groep = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &self.layout,
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: uni.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 1, resource: wgpu::BindingResource::Sampler(&self.sampler) },
                wgpu::BindGroupEntry { binding: 2, resource: wgpu::BindingResource::TextureView(&va) },
                wgpu::BindGroupEntry { binding: 3, resource: wgpu::BindingResource::TextureView(&vb) },
            ],
        });
        let mut codeur = self.device.create_command_encoder(&Default::default());
        {
            let mut pas = codeur.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("overgang"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &vd,
                    depth_slice: None,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            pas.set_pipeline(&self.pijp);
            pas.set_bind_group(0, &groep, &[]);
            pas.draw(0..4, 0..1);
        }
        codeur.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: &self.doel,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &self.uitlees,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(self.rij_bytes),
                    rows_per_image: Some(self.hoogte),
                },
            },
            wgpu::Extent3d { width: self.breedte, height: self.hoogte, depth_or_array_layers: 1 },
        );
        self.queue.submit(Some(codeur.finish()));
        let plak = self.uitlees.slice(..);
        plak.map_async(wgpu::MapMode::Read, |_| {});
        self.device.poll(wgpu::PollType::wait_indefinitely()).map_err(|e| format!("poll: {e}"))?;
        let rauw = plak.get_mapped_range();
        let rij = (self.breedte * 4) as usize;
        let mut uit = vec![0u8; rij * self.hoogte as usize];
        for y in 0..self.hoogte as usize {
            let van = y * self.rij_bytes as usize;
            uit[y * rij..(y + 1) * rij].copy_from_slice(&rauw[van..van + rij]);
        }
        drop(rauw);
        self.uitlees.unmap();
        Ok(uit)
    }
}
