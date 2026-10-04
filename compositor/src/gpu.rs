//! De wgpu-kant: texturen, pijplijnen en de volgorde van de passen.
//!
//! Metal op de Mac, DX12/Vulkan op Windows, en als er helemaal geen GPU is
//! (VM, CI-runner) de software-adapter van wgpu. Dan is het traag maar het
//! draait, en dat is precies wat een test op een runner nodig heeft.

use crate::{Afwerking, Params};
use wgpu::util::DeviceExt;

/// De shaders staan in `app/shaders/` en worden hier letterlijk ingebakken.
/// `include_str!` en niet van schijf lezen: dan kan een bevroren build nooit
/// een andere shader draaien dan waarmee hij getest is.
const LOOK_WGSL: &str = include_str!("../../app/shaders/look.wgsl");
const AFWERKING_WGSL: &str = include_str!("../../app/shaders/afwerking.wgsl");

/// Laatste stap, alleen aan deze kant: het rgba16float-beeld als RGBA8 in een
/// buffer zetten. Zelfde afronding als vroeger op de CPU (klemmen, ×255,
/// +0,5, naar beneden) — maar nu leest de CPU 4 in plaats van 8 bytes per pixel
/// terug en hoeft hij niets meer om te rekenen.
const INPAKKEN_WGSL: &str = r#"
@group(0) @binding(0) var beeld : texture_2d<f32>;
@group(0) @binding(1) var<storage, read_write> uit : array<u32>;
@group(0) @binding(2) var<uniform> maat : vec4<u32>;

@compute @workgroup_size(8, 8, 1)
fn inpakken(@builtin(global_invocation_id) id : vec3<u32>) {
  if (id.x >= maat.x || id.y >= maat.y) { return; }
  let c = textureLoad(beeld, vec2<i32>(id.xy), 0);
  let q = vec4<u32>(floor(clamp(c, vec4<f32>(0.0), vec4<f32>(1.0)) * 255.0 + 0.5));
  uit[id.y * maat.x + id.x] = q.x | (q.y << 8u) | (q.z << 16u) | (q.w << 24u);
}
"#;

const HOOGLICHT_GLOED: f32 = 185.0 / 255.0;
const HOOGLICHT_HALATION: f32 = 205.0 / 255.0;

pub struct Motor {
    device: wgpu::Device,
    queue: wgpu::Queue,
    breedte: u32,
    hoogte: u32,
    layout: wgpu::BindGroupLayout,
    pijpen: std::collections::HashMap<&'static str, wgpu::ComputePipeline>,
    invoer: wgpu::Texture,
    werk: [wgpu::Texture; 3],
    lut: wgpu::Buffer,
    lutmaat: u32,
    uitlees: [wgpu::Buffer; 2],
    slot: usize,
    wacht: std::collections::VecDeque<usize>,
    klaar: [std::sync::Arc<std::sync::atomic::AtomicBool>; 2],
    pak_pijp: wgpu::ComputePipeline,
    pak_groepen: Vec<wgpu::BindGroup>,
    pak_buf: wgpu::Buffer,
}

fn adapter(instance: &wgpu::Instance) -> Result<wgpu::Adapter, String> {
    for fallback in [false, true] {
        let opties = wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            force_fallback_adapter: fallback,
            compatible_surface: None,
        };
        if let Ok(a) = pollster::block_on(instance.request_adapter(&opties)) {
            return Ok(a);
        }
    }
    Err("geen GPU en ook geen software-adapter gevonden".into())
}

/// Naam, backend en of het een echte GPU is. Voor `cve doctor` en het
/// render-log: zonder dit kun je niet zien of de export op Metal liep of op
/// de software-adapter — en dat is een factor honderd in snelheid.
pub fn info() -> Result<(String, String), String> {
    let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor::default());
    let a = adapter(&instance)?;
    let i = a.get_info();
    let backend = if i.device_type == wgpu::DeviceType::Cpu {
        "software".to_string()
    } else {
        format!("{:?}", i.backend)
    };
    Ok((i.name, backend))
}

/// De limieten die dit beeldformaat nodig heeft, of een nette fout.
///
/// `downlevel_defaults()` zet `max_texture_dimension_2d` op 2048. Dat is genoeg
/// voor 1080p en te weinig voor 4K: een export op 3840x2160 kreeg een
/// validatiefout van wgpu, ook op een GPU die 4K prima kan (Codex-tegenlezing
/// 03-10-2026, bevinding 15). Daarom vragen we wat het canvas nodig heeft, en
/// alleen tot waar de adapter het aankan.
fn limieten(beschikbaar: &wgpu::Limits, breedte: u32, hoogte: u32) -> Result<wgpu::Limits, String> {
    let nodig = breedte.max(hoogte);
    if beschikbaar.max_texture_dimension_2d < nodig {
        return Err(format!(
            "deze GPU kan texturen tot {} pixels; {breedte}x{hoogte} vraagt {nodig}",
            beschikbaar.max_texture_dimension_2d
        ));
    }
    // De terugleesbuffer is het hele beeld in rgba16float, met rijen op een
    // veelvoud van 256 bytes. Op 8K loopt dat over de 256 MB van downlevel.
    let uitlees = (breedte as u64 * 8).div_ceil(256) * 256 * hoogte as u64;
    if beschikbaar.max_buffer_size < uitlees {
        return Err(format!(
            "deze GPU kan buffers tot {} MB; {breedte}x{hoogte} vraagt {} MB",
            beschikbaar.max_buffer_size / 1_000_000,
            uitlees / 1_000_000
        ));
    }
    let mut l = wgpu::Limits::downlevel_defaults();
    l.max_texture_dimension_2d = l.max_texture_dimension_2d.max(nodig);
    l.max_buffer_size = l.max_buffer_size.max(uitlees);
    Ok(l)
}

/// Een wgpu-apparaat met de limieten die dit beeldformaat nodig heeft.
pub fn apparaat(breedte: u32, hoogte: u32, label: &str) -> Result<(wgpu::Device, wgpu::Queue), String> {
    let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor::default());
    let adapter = adapter(&instance)?;
    let required_limits = limieten(&adapter.limits(), breedte, hoogte)
        .map_err(|e| format!("{e} (adapter: {})", adapter.get_info().name))?;
    pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor {
        label: Some(label),
        required_features: wgpu::Features::empty(),
        required_limits,
        memory_hints: wgpu::MemoryHints::Performance,
        trace: wgpu::Trace::Off,
        experimental_features: Default::default(),
    }))
    .map_err(|e| format!("geen apparaat: {e}"))
}

impl Motor {
    pub fn nieuw(breedte: u32, hoogte: u32, lutdata: &[f32], lutmaat: u32) -> Result<Self, String> {
        let (device, queue) = apparaat(breedte, hoogte, "beatcut-compositor")?;

        let layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("compositor"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 2,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::StorageTexture {
                        access: wgpu::StorageTextureAccess::WriteOnly,
                        format: wgpu::TextureFormat::Rgba16Float,
                        view_dimension: wgpu::TextureViewDimension::D2,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 3,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: true },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 4,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
            ],
        });
        let pijplayout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[&layout],
            push_constant_ranges: &[],
        });

        let mod_look = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("look.wgsl"),
            source: wgpu::ShaderSource::Wgsl(LOOK_WGSL.into()),
        });
        let mod_afw = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("afwerking.wgsl"),
            source: wgpu::ShaderSource::Wgsl(AFWERKING_WGSL.into()),
        });

        let mut pijpen = std::collections::HashMap::new();
        for (naam, module) in [
            ("look", &mod_look),
            ("hooglichten", &mod_afw),
            ("vervaag_h", &mod_afw),
            ("vervaag_v", &mod_afw),
            ("screen_meng", &mod_afw),
            ("materiaal", &mod_afw),
            ("camera", &mod_afw),
        ] {
            pijpen.insert(
                naam,
                device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                    label: Some(naam),
                    layout: Some(&pijplayout),
                    module,
                    entry_point: Some(naam),
                    compilation_options: Default::default(),
                    cache: None,
                }),
            );
        }

        let maak = |format: wgpu::TextureFormat, gebruik: wgpu::TextureUsages| {
            device.create_texture(&wgpu::TextureDescriptor {
                label: None,
                size: wgpu::Extent3d { width: breedte, height: hoogte, depth_or_array_layers: 1 },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format,
                usage: gebruik,
                view_formats: &[],
            })
        };
        let invoer = maak(
            wgpu::TextureFormat::Rgba8Unorm,
            wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
        );
        let werkgebruik = wgpu::TextureUsages::TEXTURE_BINDING
            | wgpu::TextureUsages::STORAGE_BINDING
            | wgpu::TextureUsages::COPY_SRC;
        let werk = [
            maak(wgpu::TextureFormat::Rgba16Float, werkgebruik),
            maak(wgpu::TextureFormat::Rgba16Float, werkgebruik),
            maak(wgpu::TextureFormat::Rgba16Float, werkgebruik),
        ];

        let lut = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("lut"),
            contents: bytemuck::cast_slice(lutdata),
            usage: wgpu::BufferUsages::STORAGE,
        });

        // Terugleesbuffer: wgpu wil rijen van een veelvoud van 256 bytes.
        // Twee, zodat de GPU frame k+1 kan rekenen terwijl wij frame k
        // teruglezen en wegschrijven (zie `stuur` en `haal`).
        let grootte = breedte as u64 * hoogte as u64 * 4;
        let maak_uitlees = || device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("uitlees"),
            size: grootte,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let uitlees = [maak_uitlees(), maak_uitlees()];

        let pak_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("ingepakt"),
            size: grootte,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
            mapped_at_creation: false,
        });
        let pak_mod = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("inpakken"),
            source: wgpu::ShaderSource::Wgsl(INPAKKEN_WGSL.into()),
        });
        let pak_pijp = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("inpakken"),
            layout: None,
            module: &pak_mod,
            entry_point: Some("inpakken"),
            compilation_options: Default::default(),
            cache: None,
        });
        let maat = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("maat"),
            contents: bytemuck::cast_slice(&[breedte, hoogte, 0u32, 0u32]),
            usage: wgpu::BufferUsages::UNIFORM,
        });
        // Eén bindgroep per werktextuur; welke de laatste is hangt af van de
        // afwerking.
        let pak_layout = pak_pijp.get_bind_group_layout(0);
        let pak_groepen = werk
            .iter()
            .map(|t| {
                let v = t.create_view(&Default::default());
                device.create_bind_group(&wgpu::BindGroupDescriptor {
                    label: None,
                    layout: &pak_layout,
                    entries: &[
                        wgpu::BindGroupEntry { binding: 0, resource: wgpu::BindingResource::TextureView(&v) },
                        wgpu::BindGroupEntry { binding: 1, resource: pak_buf.as_entire_binding() },
                        wgpu::BindGroupEntry { binding: 2, resource: maat.as_entire_binding() },
                    ],
                })
            })
            .collect();

        Ok(Self {
            device, queue, breedte, hoogte, layout, pijpen,
            invoer, werk, lut, lutmaat, uitlees, slot: 0,
            wacht: std::collections::VecDeque::new(),
            klaar: [Default::default(), Default::default()],
            pak_pijp, pak_groepen, pak_buf,
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn pas(
        &self, codeur: &mut wgpu::CommandEncoder, naam: &str, p: &Params,
        bron: &wgpu::TextureView, doel: &wgpu::TextureView,
        buffer: &wgpu::Buffer, tweede: &wgpu::TextureView,
    ) {
        let uni = self.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: None,
            contents: bytemuck::bytes_of(p),
            usage: wgpu::BufferUsages::UNIFORM,
        });
        let groep = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &self.layout,
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: uni.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 1, resource: wgpu::BindingResource::TextureView(bron) },
                wgpu::BindGroupEntry { binding: 2, resource: wgpu::BindingResource::TextureView(doel) },
                wgpu::BindGroupEntry { binding: 3, resource: buffer.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 4, resource: wgpu::BindingResource::TextureView(tweede) },
            ],
        });
        let mut pas = codeur.begin_compute_pass(&wgpu::ComputePassDescriptor {
            label: Some(naam),
            timestamp_writes: None,
        });
        pas.set_pipeline(&self.pijpen[naam]);
        pas.set_bind_group(0, &groep, &[]);
        pas.dispatch_workgroups(self.breedte.div_ceil(8), self.hoogte.div_ceil(8), 1);
    }

    /// Hoeveel frames er op de GPU onderweg zijn.
    pub fn onderweg(&self) -> usize {
        self.wacht.len()
    }

    /// Frame op de GPU zetten zonder op het resultaat te wachten. Hoogstens
    /// twee tegelijk (er zijn twee terugleesbuffers): haal er eerst één op.
    pub fn stuur(
        &mut self, rgba: &[u8], frame: u32, seed: u32, sterkte: f32, afw: &Afwerking,
    ) -> Result<(), String> {
        if self.wacht.len() >= self.uitlees.len() {
            return Err("twee frames onderweg; eerst haal()".into());
        }
        self.queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &self.invoer,
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

        let v_in = self.invoer.create_view(&Default::default());
        let v: Vec<wgpu::TextureView> =
            self.werk.iter().map(|t| t.create_view(&Default::default())).collect();

        let basis = Params {
            breedte: self.breedte,
            hoogte: self.hoogte,
            frame,
            seed,
            sterkte: sterkte.clamp(0.0, 1.0),
            lut_grootte: self.lutmaat,
            korrel: afw.korrel,
            vignet: afw.vignet,
            halation: afw.halation,
            gloed: afw.gloed,
            lichtlek: afw.lichtlek,
            breedbeeld: afw.breedbeeld,
            filmtrilling: afw.filmtrilling,
            kleurrand: afw.kleurrand,
            mix_r: 1.0,
            mix_g: 1.0,
            mix_b: 1.0,
            ..Default::default()
        };

        let mut codeur = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });

        // 1. kleur
        self.pas(&mut codeur, "look", &basis, &v_in, &v[0], &self.lut, &v[2]);
        let mut huidig = 0usize;

        // 2. licht: gloed en halation, in die volgorde — halation kijkt naar
        //    het beeld mét gloed, net als de ffmpeg-keten in `_lookfilter`.
        for (sterk, drempel, factor, hoogtefractie, minsigma, kleur) in [
            (afw.gloed, HOOGLICHT_GLOED, 0.75f32, 0.012f32, 1.0f32, [1.0f32, 1.0, 1.0]),
            (afw.halation, HOOGLICHT_HALATION, 0.85, 0.024, 2.0, [1.0, 0.30, 0.10]),
        ] {
            if sterk <= 0.0 {
                continue;
            }
            let sigma = (hoogtefractie * self.hoogte as f32).max(minsigma);
            let w = crate::kernel(sigma);
            let kbuf = self.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some("kernel"),
                contents: bytemuck::cast_slice(&w),
                usage: wgpu::BufferUsages::STORAGE,
            });
            let straal = (w.len() as u32 - 1) / 2;
            let a = huidig;
            let b = (huidig + 1) % 3;
            let c = (huidig + 2) % 3;

            let mut p = basis;
            p.drempel = drempel;
            self.pas(&mut codeur, "hooglichten", &p, &v[a], &v[b], &self.lut, &v[c]);
            p.straal = straal;
            self.pas(&mut codeur, "vervaag_h", &p, &v[b], &v[c], &kbuf, &v[a]);
            p.mix_r = kleur[0];
            p.mix_g = kleur[1];
            p.mix_b = kleur[2];
            self.pas(&mut codeur, "vervaag_v", &p, &v[c], &v[b], &kbuf, &v[a]);
            let mut q = basis;
            q.dekking = factor * sterk;
            self.pas(&mut codeur, "screen_meng", &q, &v[a], &v[c], &self.lut, &v[b]);
            huidig = c;
        }

        // 3. materiaal: lichtlek, korrel, vignet
        if afw.lichtlek > 0.0 || afw.korrel > 0.0 || afw.vignet > 0.0 {
            let volgend = (huidig + 1) % 3;
            self.pas(&mut codeur, "materiaal", &basis, &v[huidig], &v[volgend], &self.lut, &v[(huidig + 2) % 3]);
            huidig = volgend;
        }

        // 4. camera: kleurrand, filmtrilling, breedbeeld — alle drie hersamplen,
        //    dus één pas, anders rekent de tweede op een al hersampeld beeld.
        if afw.kleurrand > 0.0 || afw.filmtrilling > 0.0 || afw.breedbeeld > 0.0 {
            let volgend = (huidig + 1) % 3;
            self.pas(&mut codeur, "camera", &basis, &v[huidig], &v[volgend], &self.lut, &v[(huidig + 2) % 3]);
            huidig = volgend;
        }

        {
            let mut pas = codeur.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: Some("inpakken"),
                timestamp_writes: None,
            });
            pas.set_pipeline(&self.pak_pijp);
            pas.set_bind_group(0, &self.pak_groepen[huidig], &[]);
            pas.dispatch_workgroups(self.breedte.div_ceil(8), self.hoogte.div_ceil(8), 1);
        }
        codeur.copy_buffer_to_buffer(&self.pak_buf, 0, &self.uitlees[self.slot], 0, self.pak_buf.size());
        self.queue.submit(Some(codeur.finish()));
        let vlag = self.klaar[self.slot].clone();
        vlag.store(false, std::sync::atomic::Ordering::SeqCst);
        self.uitlees[self.slot].slice(..).map_async(wgpu::MapMode::Read, move |_| {
            vlag.store(true, std::sync::atomic::Ordering::SeqCst);
        });
        self.wacht.push_back(self.slot);
        self.slot = (self.slot + 1) % self.uitlees.len();
        Ok(())
    }

    /// Het oudste frame dat onderweg is, of None als er niets onderweg is.
    pub fn haal(&mut self) -> Result<Option<Vec<u8>>, String> {
        let Some(slot) = self.wacht.pop_front() else { return Ok(None) };
        let buf = &self.uitlees[slot];
        // Wachten tot déze buffer gemapt is; het volgende frame mag intussen
        // al rekenen, dus niet op álles wachten.
        while !self.klaar[slot].load(std::sync::atomic::Ordering::SeqCst) {
            self.device.poll(wgpu::PollType::Poll).map_err(|e| format!("poll: {e}"))?;
            std::thread::sleep(std::time::Duration::from_micros(100));
        }
        let rauw = buf.slice(..).get_mapped_range();
        let uit = rauw.to_vec();
        drop(rauw);
        buf.unmap();
        Ok(Some(uit))
    }
}

/// Half-precision terug naar f32, zonder extra crate. Alleen nog voor de tests:
/// het terugzetten naar 8 bits gebeurt sinds 03-10-2026 op de GPU (`INPAKKEN_WGSL`).
#[cfg(test)]
///
/// Met de hand in bits puzzelen ging hier mis: subnormale halfs (alles onder
/// 6·10⁻⁵, en dat is in een donker beeld niet zeldzaam) kwamen er als 0,22 of
/// 0,73 uit. Rekenen in plaats van schuiven is korter en heeft dat probleem niet.
fn f16_naar_f32(h: u16) -> f32 {
    let teken = if h & 0x8000 != 0 { -1.0 } else { 1.0 };
    let exp = ((h >> 10) & 0x1f) as i32;
    let mant = (h & 0x3ff) as f32;
    if exp == 0 {
        teken * mant * 5.960_464_5e-8 // 2⁻²⁴
    } else if exp == 31 {
        teken * f32::INFINITY
    } else {
        teken * (1.0 + mant / 1024.0) * 2f32.powi(exp - 15)
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn limieten_vragen_wat_het_canvas_nodig_heeft() {
        let ruim = wgpu::Limits::default();
        // 4K moet door: downlevel zegt 2048, wij vragen 3840.
        let l = super::limieten(&ruim, 3840, 2160).unwrap();
        assert!(l.max_texture_dimension_2d >= 3840);
        // 1080p mag de downlevel-standaard houden.
        let k = super::limieten(&ruim, 1920, 1080).unwrap();
        assert_eq!(k.max_texture_dimension_2d, wgpu::Limits::downlevel_defaults().max_texture_dimension_2d);
    }

    #[test]
    fn limieten_weigeren_wat_de_adapter_niet_kan() {
        let krap = wgpu::Limits::downlevel_defaults();
        let fout = super::limieten(&krap, 3840, 2160).unwrap_err();
        assert!(fout.contains("2048") && fout.contains("3840"), "{fout}");
        // Buffergrens: 8K past wel in de textuurgrens van `default()` maar
        // niet in de 256 MB buffergrens.
        let mut ruim = wgpu::Limits::default();
        ruim.max_buffer_size = 32 << 20;
        assert!(super::limieten(&ruim, 3840, 2160).is_err());
    }

    #[test]
    fn half_naar_float() {
        assert_eq!(super::f16_naar_f32(0x0000), 0.0);
        assert_eq!(super::f16_naar_f32(0x3c00), 1.0);
        assert_eq!(super::f16_naar_f32(0x3800), 0.5);
        assert_eq!(super::f16_naar_f32(0xbc00), -1.0);
        // Subnormaal: hier ging het eerder mis en kwam er 0,73 uit.
        assert!((super::f16_naar_f32(0x0001) - 5.960_464_5e-8).abs() < 1e-12);
        assert!(super::f16_naar_f32(0x03ff) < 6.11e-5);
    }
}
