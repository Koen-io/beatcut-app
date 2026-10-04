//! De kadering van de speler, headless nagemeten.
//!
//! `test_overgangen_gouden.py` meet de overgangen met het kader op de eenheid:
//! dat is wat de export meestuurt, want ffmpeg heeft de blokken dan al op
//! canvasformaat gezet. De speler stuurt iets anders mee — vulmodus (vul /
//! pas / wazig) plus Ken Burns zitten daar in `u.bronA`/`u.bronB`/`u.pasA`/
//! `u.pasB` — en die kant had tot 04-10-2026 alleen een handmeting in Chrome
//! (`ontwerp/beatcut2/qa/overgang-vulmodus.js`).
//!
//! Hier hangt dezelfde pijplijn als in `overgang.rs` de shader van de speler
//! erachter: `uniforms.wgsl` + `overgangen.wgsl` + `passthrough.wgsl` +
//! `compositor.wgsl`, letterlijk de vier bestanden die `tekenen.ts` aan elkaar
//! plakt. Zo is dit geen tweede implementatie maar dezelfde WGSL met een
//! andere uniform-buffer.
//!
//! Alleen onder `cargo test`: de export heeft hier niets aan.

use wgpu::util::DeviceExt;

const UNIFORMS_WGSL: &str = include_str!("../../app/shaders/uniforms.wgsl");
const OVERGANGEN_WGSL: &str = include_str!("../../app/shaders/overgangen.wgsl");
const PASSTHROUGH_WGSL: &str = include_str!("../../app/src/speler/passthrough.wgsl");
const COMPOSITOR_WGSL: &str = include_str!("../../app/src/speler/compositor.wgsl");

/// 16:9, en `B * 4` is een veelvoud van 256 — dan heeft de uitleesbuffer geen
/// rijopvulling en is een pixel gewoon `(y * B + x) * 4`.
const B: usize = 192;
const H: usize = 108;

/// De soortnummers uit `edl.OVERGANGEN`, in dezelfde volgorde als de
/// constanten in `overgangen.wgsl`.
const O_SNEDE: u32 = 0;
const O_CROSSFADE: u32 = 1;
const O_PIXEL: u32 = 5;

const VUL: f32 = 0.0;
const PAS: f32 = 1.0;
const WAZIG: f32 = 2.0;

/// Een staande bron (9:16) in een liggend canvas: dan zijn de drie vulmodi
/// echt verschillend en heeft `pas` balken om links en rechts.
const BRON_VERHOUDING: f32 = 9.0 / 16.0;

struct Proef {
    device: wgpu::Device,
    queue: wgpu::Queue,
    pijp: wgpu::RenderPipeline,
    layout: wgpu::BindGroupLayout,
    sampler: wgpu::Sampler,
    a: wgpu::Texture,
    b: wgpu::Texture,
    doel: wgpu::Texture,
    uitlees: wgpu::Buffer,
}

impl Proef {
    fn nieuw() -> Result<Self, String> {
        let (device, queue) = crate::gpu::apparaat(B as u32, H as u32, "beatcut-spelerproef")?;
        let bron =
            format!("{UNIFORMS_WGSL}\n{OVERGANGEN_WGSL}\n{PASSTHROUGH_WGSL}\n{COMPOSITOR_WGSL}");
        let module = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("spelerproef"),
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
            label: Some("spelerproef"),
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
            label: Some("spelerproef"),
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
        // Zelfde sampler als `tekenen.ts` en als de export: lineair, geklemd.
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });
        let maak = |gebruik: wgpu::TextureUsages| {
            device.create_texture(&wgpu::TextureDescriptor {
                label: None,
                size: wgpu::Extent3d {
                    width: B as u32,
                    height: H as u32,
                    depth_or_array_layers: 1,
                },
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
        let uitlees = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("spelerproef-uitlees"),
            size: (B * H * 4) as u64,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        Ok(Self { device, queue, pijp, layout, sampler, a, b, doel, uitlees })
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
                bytes_per_row: Some((B * 4) as u32),
                rows_per_image: Some(H as u32),
            },
            wgpu::Extent3d { width: B as u32, height: H as u32, depth_or_array_layers: 1 },
        );
    }

    /// Eén frame zoals de speler het zou tekenen, als RGBA8.
    fn beeld(&self, a: &[u8], b: &[u8], u: &[f32; 36]) -> Vec<u8> {
        self.schrijf(&self.a, a);
        self.schrijf(&self.b, b);
        let uni = self.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: None,
            contents: bytemuck::cast_slice(u),
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
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&self.sampler),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::TextureView(&va),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: wgpu::BindingResource::TextureView(&vb),
                },
            ],
        });
        let mut codeur = self.device.create_command_encoder(&Default::default());
        {
            let mut pas = codeur.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("spelerproef"),
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
                    bytes_per_row: Some((B * 4) as u32),
                    rows_per_image: Some(H as u32),
                },
            },
            wgpu::Extent3d { width: B as u32, height: H as u32, depth_or_array_layers: 1 },
        );
        self.queue.submit(Some(codeur.finish()));
        let plak = self.uitlees.slice(..);
        plak.map_async(wgpu::MapMode::Read, |_| {});
        self.device.poll(wgpu::PollType::wait_indefinitely()).expect("poll");
        let uit = plak.get_mapped_range().to_vec();
        self.uitlees.unmap();
        uit
    }
}

/// `kaderVul()` uit `app/src/speler/uniforms.ts`, met zoom 1 en pan 0.
fn kader_vul(bron: f32, canvas: f32) -> [f32; 4] {
    let mut w = 1.0f32;
    let mut h = 1.0f32;
    if bron > canvas {
        w *= canvas / bron;
    } else {
        h *= bron / canvas;
    }
    [w, h, (1.0 - w) / 2.0, (1.0 - h) / 2.0]
}

/// `kaderPas()` uit `app/src/speler/uniforms.ts`.
fn kader_pas(bron: f32, canvas: f32) -> [f32; 4] {
    let mut w = 1.0f32;
    let mut h = 1.0f32;
    if bron > canvas {
        h = bron / canvas;
    } else {
        w = canvas / bron;
    }
    [w, h, (1.0 - w) / 2.0, (1.0 - h) / 2.0]
}

/// De negen vec4's van `struct Uniforms`, zoals `schrijfUniforms()` ze vult.
fn uniformen(soort: u32, meng: f32, vulmodus: f32) -> [f32; 36] {
    let canvas = B as f32 / H as f32;
    let vul = kader_vul(BRON_VERHOUDING, canvas);
    let pas = kader_pas(BRON_VERHOUDING, canvas);
    let mut u = [0f32; 36];
    u[0..4].copy_from_slice(&vul);
    u[4..8].copy_from_slice(&vul);
    u[8..12].copy_from_slice(&pas);
    u[12..16].copy_from_slice(&pas);
    u[16] = meng;
    u[17] = soort as f32;
    u[18] = vulmodus;
    u[19] = vulmodus;
    u[20] = 2.0 / 30.0; // tijdlijntijd
    u[21] = 2.0; // frame-index
    u[22] = 7.0; // effectseed
    u[23] = canvas;
    u[24] = 1.0; // looksterkte; de passthrough doet er niets mee
    u
}

/// Witte ruis: elke pixel staat los van zijn buren. Een scherp beeld heeft
/// daarmee bijna geen twee gelijke buren, en blokkigheid is dus echt
/// blokkigheid en niet een vlak stuk lucht.
fn bronbeeld(zaad: u32) -> Vec<u8> {
    let mut v = vec![0u8; B * H * 4];
    for y in 0..H {
        for x in 0..B {
            let n = (x as u32)
                .wrapping_mul(73)
                .wrapping_add((y as u32).wrapping_mul(151))
                .wrapping_add(zaad.wrapping_mul(997));
            let m = n.wrapping_mul(2654435761).rotate_left(13).wrapping_mul(2246822519);
            let i = (y * B + x) * 4;
            v[i] = (m & 0xff) as u8;
            v[i + 1] = ((m >> 11) & 0xff) as u8;
            v[i + 2] = ((m >> 21) & 0xff) as u8;
            v[i + 3] = 255;
        }
    }
    v
}

/// Een vloeiend beeld: twee lineaire verlopen over elkaar. Hiermee is een
/// verschil in codes ook echt een verschil in *beeld* — witte ruis heeft een
/// sprong van honderden codes tussen twee buurpixels, en dan meet je met een
/// verschuiving van een honderdste pixel al tien codes die niemand ziet.
fn bronbeeld_vloeiend(zaad: u32) -> Vec<u8> {
    let mut v = vec![0u8; B * H * 4];
    for y in 0..H {
        for x in 0..B {
            let i = (y * B + x) * 4;
            let schuif = (zaad * 37 % 64) as usize;
            v[i] = ((x + schuif) * 200 / B) as u8;
            v[i + 1] = ((y + schuif) * 200 / H) as u8;
            v[i + 2] = ((x + y + schuif) * 200 / (B + H)) as u8;
            v[i + 3] = 255;
        }
    }
    v
}

/// Het meetvenster: de kolommen waar in vulmodus `pas` het beeld staat, met
/// een marge van 2 % van het canvas zodat de rand van de balk niet meedoet.
/// Buiten dat venster staat bij `pas` zwart en bij `wazig` de wazige vulling —
/// allebei vlak, en dat zou elke blokkigheidsmeting gratis laten slagen.
fn venster() -> (usize, usize, usize, usize) {
    let canvas = B as f32 / H as f32;
    let [w, h, sx, sy] = kader_pas(BRON_VERHOUDING, canvas);
    let marge = 0.02;
    let strook = |schaal: f32, schuif: f32, n: usize| -> (usize, usize) {
        let van = (-schuif / schaal + marge) * n as f32;
        let tot = ((1.0 - schuif) / schaal - marge) * n as f32;
        (van.ceil().max(0.0) as usize, (tot.floor() as usize).min(n))
    };
    let (x0, x1) = strook(w, sx, B);
    let (y0, y1) = strook(h, sy, H);
    (x0, y0, x1, y1)
}

/// Welk deel van de buurparen in het venster byte voor byte gelijk is. Een
/// mozaïek van 20 bij 11 blokken op 192 bij 108 pixels zit rond 0,9; een
/// scherp beeld van witte ruis rond 0,0.
fn blokkigheid(beeld: &[u8], venster: (usize, usize, usize, usize)) -> f32 {
    let (x0, y0, x1, y1) = venster;
    let px = |x: usize, y: usize| -> [u8; 3] {
        let i = (y * B + x) * 4;
        [beeld[i], beeld[i + 1], beeld[i + 2]]
    };
    let mut gelijk = 0usize;
    let mut paren = 0usize;
    for y in y0..y1 {
        for x in x0..x1 {
            if x + 1 < x1 {
                paren += 1;
                if px(x, y) == px(x + 1, y) {
                    gelijk += 1;
                }
            }
            if y + 1 < y1 {
                paren += 1;
                if px(x, y) == px(x, y + 1) {
                    gelijk += 1;
                }
            }
        }
    }
    assert!(paren > 1000, "meetvenster te klein: {paren} paren");
    gelijk as f32 / paren as f32
}

/// De grootste afwijking in codes tussen twee frames, over R, G en B.
fn verschil(a: &[u8], b: &[u8]) -> u8 {
    let mut max = 0u8;
    for i in (0..a.len()).step_by(4) {
        for k in 0..3 {
            max = max.max(a[i + k].abs_diff(b[i + k]));
        }
    }
    max
}

#[test]
fn het_mozaiek_van_pixel_is_in_alle_drie_de_vulmodi_zichtbaar() {
    let proef = match Proef::nieuw() {
        Ok(p) => p,
        Err(e) => {
            eprintln!("geen GPU op deze machine, test overgeslagen: {e}");
            return;
        }
    };
    let (a, b) = (bronbeeld(1), bronbeeld(2));
    let v = venster();
    let mut gezakt: Vec<String> = Vec::new();

    // De controle: een crossfade halverwege is geen mozaïek en hoort dus in
    // elke vulmodus scherp te zijn. Zonder deze meting zou "blokkig" ook
    // kunnen betekenen "er staat niets in beeld".
    for (naam, modus) in [("vul", VUL), ("pas", PAS), ("wazig", WAZIG)] {
        let scherp = proef.beeld(&a, &b, &uniformen(O_CROSSFADE, 0.5, modus));
        let bk = blokkigheid(&scherp, v);
        println!("  crossfade/{naam:<5} blokkigheid {bk:.3} (lat < 0,3)");
        assert!(bk < 0.3, "crossfade/{naam} is niet scherp: blokkigheid {bk:.3}");
    }

    // En dit is waar het om gaat: `pixel` halverwege staat op het grofste
    // raster (11 blokken hoog), en dat hoort je in alle drie de vulmodi te
    // zien. Tot 04-10-2026 kwantiseerde `overgang_uv()` alleen het vul-kader,
    // terwijl `o_samenstel()` bij `pas` en `wazig` het pas-kader in beeld
    // brengt — daar bleef het beeld dus haarscherp (brein-taak
    // 20261003-181243).
    for (naam, modus) in [("vul", VUL), ("pas", PAS), ("wazig", WAZIG)] {
        let mozaiek = proef.beeld(&a, &b, &uniformen(O_PIXEL, 0.5, modus));
        let bk = blokkigheid(&mozaiek, v);
        println!("  pixel/{naam:<9} blokkigheid {bk:.3} (lat > 0,7)");
        if bk <= 0.7 {
            gezakt.push(format!("pixel/{naam} is niet blokkig: blokkigheid {bk:.3}"));
        }
    }
    // Alle drie meten en dán pas falen: zakt er één modus, dan wil je de
    // andere twee er ook bij hebben staan. Dat is precies het verschil tussen
    // "pixel is stuk" en "pixel is stuk in pas en wazig, en dus in de kadering".
    assert!(gezakt.is_empty(), "{}", gezakt.join("; "));
}

#[test]
fn pixel_staat_op_t0_in_pas_en_wazig_niet_verder_van_het_snedeframe_dan_in_vul() {
    let proef = match Proef::nieuw() {
        Ok(p) => p,
        Err(e) => {
            eprintln!("geen GPU op deze machine, test overgeslagen: {e}");
            return;
        }
    };
    let (a, b) = (bronbeeld_vloeiend(1), bronbeeld_vloeiend(2));

    // Het raster is op t = 0 zo fijn (4096 blokken hoog) dat er niets van te
    // zien hoort te zijn: het snedeframe is bron A, met balken en al. Het
    // monster schuift een halve blokbreedte op — 0,013 canvaspixel — en op
    // vloeiend beeld is dat geen enkele code.
    //
    // Dit is de meting die het pas-kader in de gaten houdt: dat kader schaalt
    // een staande bron 3,16 keer op, dus een fout in de uv's slaat daar harder
    // door dan in `vul`. Zou `pixel` per ongeluk het vul-monster in het
    // pas-kader zetten, dan staat hier tientallen codes verschil.
    let afwijking = |modus: f32| -> u8 {
        let snede = proef.beeld(&a, &b, &uniformen(O_SNEDE, 0.0, modus));
        let begin = proef.beeld(&a, &b, &uniformen(O_PIXEL, 0.0, modus));
        verschil(&snede, &begin)
    };
    let basis = afwijking(VUL);
    println!("  t=0, codes van het snedeframe af: vul {basis}");
    for (naam, modus) in [("pas", PAS), ("wazig", WAZIG)] {
        let d = afwijking(modus);
        println!("  t=0, codes van het snedeframe af: {naam} {d} (lat {})", basis.max(1));
        assert!(
            d <= basis.max(1),
            "pixel/{naam} wijkt op t=0 {d} codes van het snedeframe af, vul {basis}"
        );
    }
}
