// De WebGPU-kant van de speler: eerst het beeld samenstellen, dan de look en de
// afwerking, dan op het canvas.
//
// De keten is bewust dezelfde als die van de export (`compositor/src/gpu.rs`):
//
//   1. render-pas  — overgangen.wgsl + compositor.wgsl: twee bronbeelden,
//      vulmodus, Ken Burns en de overgang, naar een eigen textuur (geen canvas)
//   2. reken-passen — look.wgsl en afwerking.wgsl uit `app/shaders/`, letterlijk
//      dezelfde bestanden als de native compositor inbakt, in dezelfde volgorde
//      en met dezelfde uniformwaarden
//   3. blit        — het resultaat op het canvas
//
// Punt 2 is de hele reden dat dit bestand bestaat: PLAN-v2.md §4.4 wil één set
// WGSL voor voorvertoning én export. Daarom staan de passen hier niet opnieuw
// uitgerekend maar precies in de volgorde van `Motor::frame()` in gpu.rs. Wijkt
// die volgorde af, dan is de voorvertoning een andere film dan de export.
import { WGSL_UNIFORMS, BYTES, schrijfUniforms, type Kader, type Stand } from "./uniforms";
import compositorWgsl from "./compositor.wgsl?raw";
import passthroughWgsl from "./passthrough.wgsl?raw";
import blitWgsl from "./blit.wgsl?raw";
// De twee gedeelde shaders. Letterlijk ingelezen, net als `include_str!` in
// gpu.rs: nooit een tweede implementatie, want die wijkt vroeg of laat af.
import overgangenWgsl from "../../shaders/overgangen.wgsl?raw";
import lookWgsl from "../../shaders/look.wgsl?raw";
import afwerkingWgsl from "../../shaders/afwerking.wgsl?raw";
import { identiteit, type Lut } from "./lut";
import {
  GEEN_AFWERKING,
  HOOGLICHT_GLOED,
  HOOGLICHT_HALATION,
  PARAMS_BYTES,
  afwerkingUitLijst,
  f16NaarF32,
  kernel,
  schrijfParams,
  type Afwerking,
  type Velden,
} from "./params";

/** De namen van de rekenpassen, zoals ze in de WGSL staan. */
const PASSEN = ["look", "hooglichten", "vervaag_h", "vervaag_v", "screen_meng", "materiaal", "camera"] as const;
type Pas = (typeof PASSEN)[number];

/** Wat de keten nodig heeft als hij los van de tijdlijn gedraaid wordt (QA). */
export type Keten = {
  frame: number;
  seed: number;
  sterkte: number;
  afwerking: Afwerking;
};

/** Eén overgangsmoment, los van de tijdlijn (QA). Dezelfde velden als
 *  `overgang::Moment` in de export. */
export type Moment = {
  soort: number;
  meng: number;
  frame: number;
  tijd: number;
  seed: number;
};

/** Het inpaskader plus de vulmodus van twee bronnen; zie `overgangOp`. */
export type Inpassing = {
  vulmodusA: number;
  vulmodusB: number;
  pasA: Kader;
  pasB: Kader;
};

export type Doek = {
  tekenGereed: boolean;
  /** Zet één frame op het canvas. `b` mag null zijn (geen overgang bezig). */
  teken(a: VideoFrame | null, b: VideoFrame | null, stand: Stand): void;
  formaat(breedte: number, hoogte: number): void;
  /** De kleurtabel van de gekozen look. Zonder aanroep: identiteit. */
  zetLut(lut: Lut): void;
  /** QA: het samengestelde beeld vóór de look, als RGBA8 — precies wat de
   *  native compositor op zijn stdin krijgt. */
  grijpBron(): Promise<Uint8Array>;
  /** QA: look + afwerking op een gegeven RGBA8-beeld, zonder de tijdlijn. */
  ketenOp(bron: Uint8Array, breedte: number, hoogte: number, k: Keten): Promise<Uint8Array>;
  /** QA: één overgangsmoment op twee gegeven bronbeelden, kader op de
   *  eenheid — precies de stand waarin `compositor/src/overgang.rs` werkt.
   *  Daarna gaat het door dezelfde look en afwerking als `teken()`. */
  overgangOp(
    a: Uint8Array,
    b: Uint8Array,
    breedte: number,
    hoogte: number,
    m: Moment,
    k: Keten,
    /** Alleen voor de QA: het inpaskader en de vulmodus van de twee bronnen.
     *  Zonder dit staat alles op de eenheid en op "vul" — de stand waarin de
     *  export rekent. Mét dit is te meten dat `pas` en `wazig` een bijzondere
     *  overgang overleven. */
    inpassing?: Inpassing,
  ): Promise<Uint8Array>;
  sluit(): void;
  herkomst: string;
  /** Welk formaat de werktexturen hebben. Zie `opslagformaat()` hieronder. */
  opslag: GPUTextureFormat;
};

/** Accepteert deze webview `rgba16float` als storage-textuur?
 *
 *  Het hoort te mogen — rgba16float staat in de WebGPU-spec bij de formaten die
 *  `write-only` storage ondersteunen, zonder extra feature. WebKit liep daar in
 *  het verleden achter, dus het wordt gemeten in plaats van aangenomen: lukt het
 *  niet, dan rgba8unorm (óók altijd toegestaan). De wiskunde blijft gelijk —
 *  geen enkele pas in de keten levert een waarde boven 1 of onder 0 op, dus er
 *  wordt niets afgekapt; alleen de tussenstappen hebben dan 8 bits in plaats
 *  van 11. De shaderbron wordt daarvoor tekstueel omgezet, want het formaat
 *  staat in de WGSL zelf.
 */
function opslagformaat(device: GPUDevice): GPUTextureFormat {
  try {
    const t = device.createTexture({
      size: [8, 8],
      format: "rgba16float",
      usage: GPUTextureUsage.STORAGE_BINDING | GPUTextureUsage.TEXTURE_BINDING,
    });
    t.destroy();
    return "rgba16float";
  } catch {
    return "rgba8unorm";
  }
}

export async function maakDoek(canvas: HTMLCanvasElement): Promise<Doek> {
  const gpu = navigator.gpu;
  if (!gpu) throw new Error("WebGPU is niet beschikbaar in deze webview");
  const adapter = await gpu.requestAdapter();
  if (!adapter) throw new Error("geen WebGPU-adapter");
  const device = await adapter.requestDevice();
  const ctx = canvas.getContext("webgpu");
  if (!ctx) throw new Error("geen webgpu-context op het canvas");
  const canvasFormaat = navigator.gpu.getPreferredCanvasFormat();
  ctx.configure({ device, format: canvasFormaat, alphaMode: "opaque" });

  const opslag = opslagformaat(device);
  const shaderbron = (tekst: string) =>
    opslag === "rgba16float" ? tekst : tekst.split("rgba16float").join(opslag);

  // -- de samenstel-pas ----------------------------------------------------
  // `look()` is hier altijd de passthrough: de echte look draait hierna als
  // rekenpas, op het hele samengestelde beeld — net als in de export.
  const samenstelModule = device.createShaderModule({
    label: "samenstellen",
    code: [WGSL_UNIFORMS, overgangenWgsl, passthroughWgsl, compositorWgsl].join("\n"),
  });
  const samenstelPijp = device.createRenderPipeline({
    layout: "auto",
    vertex: { module: samenstelModule, entryPoint: "vs" },
    fragment: { module: samenstelModule, entryPoint: "fs", targets: [{ format: opslag }] },
    primitive: { topology: "triangle-strip" },
  });

  // -- de rekenpassen ------------------------------------------------------
  const rekenLayout = device.createBindGroupLayout({
    label: "compositor",
    entries: [
      { binding: 0, visibility: GPUShaderStage.COMPUTE, buffer: { type: "uniform" } },
      { binding: 1, visibility: GPUShaderStage.COMPUTE, texture: { sampleType: "float" } },
      { binding: 2, visibility: GPUShaderStage.COMPUTE, storageTexture: { access: "write-only", format: opslag } },
      { binding: 3, visibility: GPUShaderStage.COMPUTE, buffer: { type: "read-only-storage" } },
      { binding: 4, visibility: GPUShaderStage.COMPUTE, texture: { sampleType: "float" } },
    ],
  });
  const rekenPijplayout = device.createPipelineLayout({ bindGroupLayouts: [rekenLayout] });
  const modLook = device.createShaderModule({ label: "look.wgsl", code: shaderbron(lookWgsl) });
  const modAfw = device.createShaderModule({ label: "afwerking.wgsl", code: shaderbron(afwerkingWgsl) });
  const pijpen = new Map<Pas, GPUComputePipeline>();
  for (const naam of PASSEN) {
    pijpen.set(
      naam,
      device.createComputePipeline({
        label: naam,
        layout: rekenPijplayout,
        compute: { module: naam === "look" ? modLook : modAfw, entryPoint: naam },
      }),
    );
  }

  // -- de blit naar het canvas --------------------------------------------
  const blitModule = device.createShaderModule({ label: "blit", code: blitWgsl });
  const blitPijp = device.createRenderPipeline({
    layout: "auto",
    vertex: { module: blitModule, entryPoint: "vs" },
    fragment: { module: blitModule, entryPoint: "fs", targets: [{ format: canvasFormaat }] },
    primitive: { topology: "triangle-strip" },
  });

  const uniformBuffer = device.createBuffer({
    size: BYTES,
    usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
  });
  const sampler = device.createSampler({ magFilter: "linear", minFilter: "linear" });
  const velden = new Float32Array(BYTES / 4);

  let lut = maakLutBuffer(identiteit());
  function maakLutBuffer(l: Lut): { buffer: GPUBuffer; maat: number } {
    const buffer = device.createBuffer({
      size: Math.max(16, l.data.byteLength),
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
    });
    device.queue.writeBuffer(buffer, 0, l.data);
    return { buffer, maat: l.maat };
  }

  /** Eén uniform-buffer per pas: binnen één opdracht verschillen de waarden
   *  (drempel, dekking, straal), dus hergebruiken kan niet. */
  const uniPool: GPUBuffer[] = [];
  function uni(i: number, v: Velden): GPUBuffer {
    while (uniPool.length <= i) {
      uniPool.push(
        device.createBuffer({ size: PARAMS_BYTES, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST }),
      );
    }
    device.queue.writeBuffer(uniPool[i], 0, schrijfParams(v));
    return uniPool[i];
  }

  /** Kernels hangen alleen aan de beeldhoogte; één keer uitrekenen is genoeg. */
  const kernels = new Map<string, { buffer: GPUBuffer; straal: number }>();
  function kernelBuffer(naam: string, sigma: number) {
    const sleutel = `${naam}:${sigma.toFixed(3)}`;
    const bestaand = kernels.get(sleutel);
    if (bestaand) return bestaand;
    const w = kernel(sigma);
    const buffer = device.createBuffer({
      size: w.byteLength,
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
    });
    device.queue.writeBuffer(buffer, 0, w);
    const nieuw = { buffer, straal: (w.length - 1) / 2 };
    kernels.set(sleutel, nieuw);
    return nieuw;
  }

  // -- texturen ------------------------------------------------------------
  /** Het samengestelde beeld (de invoer van de keten) en drie werktexturen,
   *  precies zoals gpu.rs: de passen wisselen er met modulo 3 tussen. */
  let maat = { b: 0, h: 0 };
  let composiet: GPUTexture | null = null;
  let werk: GPUTexture[] = [];
  let uitlees: GPUBuffer | null = null;
  let rijBytes = 0;

  function zetMaat(b: number, h: number) {
    if (maat.b === b && maat.h === h) return;
    composiet?.destroy();
    for (const t of werk) t.destroy();
    uitlees?.destroy();
    const stap = opslag === "rgba16float" ? 8 : 4;
    composiet = device.createTexture({
      size: [b, h],
      format: opslag,
      usage:
        GPUTextureUsage.RENDER_ATTACHMENT |
        GPUTextureUsage.TEXTURE_BINDING |
        GPUTextureUsage.STORAGE_BINDING |
        GPUTextureUsage.COPY_SRC |
        GPUTextureUsage.COPY_DST,
    });
    werk = [0, 1, 2].map(() =>
      device.createTexture({
        size: [b, h],
        format: opslag,
        usage:
          GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.STORAGE_BINDING | GPUTextureUsage.COPY_SRC,
      }),
    );
    rijBytes = Math.ceil((b * stap) / 256) * 256;
    uitlees = device.createBuffer({
      size: rijBytes * h,
      usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ,
    });
    maat = { b, h };
  }

  /** Twee beeldplekken voor de bronframes. Een textuur wordt opnieuw gemaakt
   *  zodra het frame een ander formaat heeft — proxies verschillen soms. */
  const plek: { tex: GPUTexture | null; b: number; h: number }[] = [
    { tex: null, b: 0, h: 0 },
    { tex: null, b: 0, h: 0 },
  ];
  const leeg = device.createTexture({
    size: [1, 1],
    format: "rgba8unorm",
    usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST | GPUTextureUsage.RENDER_ATTACHMENT,
  });

  function zet(i: number, frame: VideoFrame | null): GPUTexture {
    if (!frame) return leeg;
    const b = frame.displayWidth || frame.codedWidth;
    const h = frame.displayHeight || frame.codedHeight;
    const p = plek[i];
    if (!p.tex || p.b !== b || p.h !== h) {
      p.tex?.destroy();
      p.tex = device.createTexture({
        size: [b, h],
        format: "rgba8unorm",
        usage:
          GPUTextureUsage.TEXTURE_BINDING |
          GPUTextureUsage.COPY_DST |
          GPUTextureUsage.RENDER_ATTACHMENT,
      });
      p.b = b;
      p.h = h;
    }
    device.queue.copyExternalImageToTexture({ source: frame }, { texture: p.tex }, [b, h]);
    return p.tex;
  }

  // -- de keten ------------------------------------------------------------
  /** Eén rekenpas, met dezelfde vijf bindings als `Motor::pas()` in gpu.rs. */
  function pas(
    codeur: GPUCommandEncoder,
    teller: { n: number },
    naam: Pas,
    v: Velden,
    bron: GPUTextureView,
    doel: GPUTextureView,
    buffer: GPUBuffer,
    tweede: GPUTextureView,
  ) {
    const groep = device.createBindGroup({
      layout: rekenLayout,
      entries: [
        { binding: 0, resource: { buffer: uni(teller.n++, v) } },
        { binding: 1, resource: bron },
        { binding: 2, resource: doel },
        { binding: 3, resource: { buffer } },
        { binding: 4, resource: tweede },
      ],
    });
    const p = codeur.beginComputePass({ label: naam });
    p.setPipeline(pijpen.get(naam)!);
    p.setBindGroup(0, groep);
    p.dispatchWorkgroups(Math.ceil(maat.b / 8), Math.ceil(maat.h / 8), 1);
    p.end();
  }

  /** De hele keten op `bronView`. Geeft terug in welke werktextuur het
   *  eindresultaat staat. Volgorde en waarden: `Motor::frame()` in gpu.rs. */
  function keten(codeur: GPUCommandEncoder, bronView: GPUTextureView, k: Keten): number {
    const teller = { n: 0 };
    const v: GPUTextureView[] = werk.map((t) => t.createView());
    const basis: Velden = {
      breedte: maat.b,
      hoogte: maat.h,
      frame: k.frame,
      seed: k.seed,
      sterkte: k.sterkte,
      lutGrootte: lut.maat,
      afwerking: k.afwerking,
    };

    // 1. kleur
    pas(codeur, teller, "look", basis, bronView, v[0], lut.buffer, v[2]);
    let huidig = 0;

    // 2. licht: gloed en halation, in die volgorde — halation kijkt naar het
    //    beeld mét gloed, net als de ffmpeg-keten in `render._lookfilter`.
    const takken: { sterk: number; drempel: number; factor: number; fractie: number; min: number; kleur: [number, number, number]; naam: string }[] = [
      { sterk: k.afwerking.gloed, drempel: HOOGLICHT_GLOED, factor: 0.75, fractie: 0.012, min: 1.0, kleur: [1, 1, 1], naam: "gloed" },
      { sterk: k.afwerking.halation, drempel: HOOGLICHT_HALATION, factor: 0.85, fractie: 0.024, min: 2.0, kleur: [1, 0.3, 0.1], naam: "halation" },
    ];
    for (const tak of takken) {
      if (tak.sterk <= 0) continue;
      const sigma = Math.max(tak.fractie * maat.h, tak.min);
      const kb = kernelBuffer(tak.naam, sigma);
      const a = huidig;
      const b = (huidig + 1) % 3;
      const c = (huidig + 2) % 3;
      pas(codeur, teller, "hooglichten", { ...basis, drempel: tak.drempel }, v[a], v[b], lut.buffer, v[c]);
      pas(codeur, teller, "vervaag_h", { ...basis, drempel: tak.drempel, straal: kb.straal }, v[b], v[c], kb.buffer, v[a]);
      pas(
        codeur, teller, "vervaag_v",
        { ...basis, drempel: tak.drempel, straal: kb.straal, mix: tak.kleur },
        v[c], v[b], kb.buffer, v[a],
      );
      pas(codeur, teller, "screen_meng", { ...basis, dekking: tak.factor * tak.sterk }, v[a], v[c], lut.buffer, v[b]);
      huidig = c;
    }

    // 3. materiaal: lichtlek, korrel, vignet
    const a = k.afwerking;
    if (a.lichtlek > 0 || a.korrel > 0 || a.vignet > 0) {
      const volgend = (huidig + 1) % 3;
      pas(codeur, teller, "materiaal", basis, v[huidig], v[volgend], lut.buffer, v[(huidig + 2) % 3]);
      huidig = volgend;
    }

    // 4. camera: kleurrand, filmtrilling, breedbeeld — alle drie hersamplen,
    //    dus één pas, anders rekent de tweede op een al hersampeld beeld.
    if (a.kleurrand > 0 || a.filmtrilling > 0 || a.breedbeeld > 0) {
      const volgend = (huidig + 1) % 3;
      pas(codeur, teller, "camera", basis, v[huidig], v[volgend], lut.buffer, v[(huidig + 2) % 3]);
      huidig = volgend;
    }
    return huidig;
  }

  /** Een textuur terugleze als RGBA8, met dezelfde afronding als gpu.rs. */
  async function lees(tex: GPUTexture): Promise<Uint8Array> {
    const { b, h } = maat;
    const stap = opslag === "rgba16float" ? 8 : 4;
    const codeur = device.createCommandEncoder();
    codeur.copyTextureToBuffer(
      { texture: tex },
      { buffer: uitlees!, bytesPerRow: rijBytes, rowsPerImage: h },
      [b, h, 1],
    );
    device.queue.submit([codeur.finish()]);
    await uitlees!.mapAsync(GPUMapMode.READ);
    const rauw = new Uint8Array(uitlees!.getMappedRange().slice(0));
    uitlees!.unmap();
    const uit = new Uint8Array(b * h * 4);
    const halfs = stap === 8 ? new DataView(rauw.buffer) : null;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < b; x++) {
        for (let k = 0; k < 4; k++) {
          const i = y * rijBytes + (x * 4 + k) * (stap / 4);
          const f = halfs ? f16NaarF32(halfs.getUint16(i, true)) : rauw[i] / 255;
          uit[(y * b + x) * 4 + k] = Math.floor(Math.min(1, Math.max(0, f)) * 255 + 0.5);
        }
      }
    }
    return uit;
  }

  return {
    tekenGereed: true,
    herkomst: "app/shaders/look.wgsl + afwerking.wgsl",
    opslag,
    formaat(breedte, hoogte) {
      canvas.width = Math.max(1, Math.round(breedte));
      canvas.height = Math.max(1, Math.round(hoogte));
      zetMaat(canvas.width, canvas.height);
    },
    zetLut(nieuw) {
      lut.buffer.destroy();
      lut = maakLutBuffer(nieuw);
    },
    teken(a, b, stand) {
      zetMaat(canvas.width, canvas.height);
      device.queue.writeBuffer(uniformBuffer, 0, schrijfUniforms(stand, velden));
      const texA = zet(0, a);
      const texB = zet(1, b ?? a);
      const groep = device.createBindGroup({
        layout: samenstelPijp.getBindGroupLayout(0),
        entries: [
          { binding: 0, resource: { buffer: uniformBuffer } },
          { binding: 1, resource: sampler },
          { binding: 2, resource: texA.createView() },
          { binding: 3, resource: texB.createView() },
        ],
      });
      const codeur = device.createCommandEncoder();
      const samen = codeur.beginRenderPass({
        colorAttachments: [
          {
            view: composiet!.createView(),
            clearValue: { r: 0, g: 0, b: 0, a: 1 },
            loadOp: "clear",
            storeOp: "store",
          },
        ],
      });
      samen.setPipeline(samenstelPijp);
      samen.setBindGroup(0, groep);
      samen.draw(4);
      samen.end();

      const eind = keten(codeur, composiet!.createView(), {
        frame: stand.frame,
        seed: stand.seed,
        sterkte: stand.looksterkte,
        afwerking: afwerkingUitLijst(stand.afwerking),
      });

      const blit = codeur.beginRenderPass({
        colorAttachments: [
          {
            view: ctx.getCurrentTexture().createView(),
            clearValue: { r: 0, g: 0, b: 0, a: 1 },
            loadOp: "clear",
            storeOp: "store",
          },
        ],
      });
      blit.setPipeline(blitPijp);
      blit.setBindGroup(
        0,
        device.createBindGroup({
          layout: blitPijp.getBindGroupLayout(0),
          entries: [{ binding: 0, resource: werk[eind].createView() }],
        }),
      );
      blit.draw(4);
      blit.end();
      device.queue.submit([codeur.finish()]);
    },
    grijpBron() {
      return lees(composiet!);
    },
    async ketenOp(bron, breedte, hoogte, k) {
      zetMaat(breedte, hoogte);
      // Het beeld komt als RGBA8 binnen, net als op de stdin van de native
      // compositor. Een tussentextuur van hetzelfde formaat als de werkplekken
      // zou het al herschalen; daarom eerst naar rgba8 en dan kopiëren.
      const invoer = device.createTexture({
        size: [breedte, hoogte],
        format: "rgba8unorm",
        usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST,
      });
      device.queue.writeTexture({ texture: invoer }, bron, { bytesPerRow: breedte * 4 }, [breedte, hoogte]);
      const codeur = device.createCommandEncoder();
      const eind = keten(codeur, invoer.createView(), k);
      device.queue.submit([codeur.finish()]);
      const uit = await lees(werk[eind]);
      invoer.destroy();
      return uit;
    },
    async overgangOp(a, b, breedte, hoogte, m, k, inpassing) {
      zetMaat(breedte, hoogte);
      const invoer = (bytes: Uint8Array) => {
        const t = device.createTexture({
          size: [breedte, hoogte],
          format: "rgba8unorm",
          usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST,
        });
        device.queue.writeTexture({ texture: t }, bytes, { bytesPerRow: breedte * 4 }, [breedte, hoogte]);
        return t;
      };
      const texA = invoer(a);
      const texB = invoer(b);
      // Het kader op de eenheid en vulmodus "vul": in de export heeft ffmpeg
      // het inpassen en Ken Burns al in het blok gebakken, dus staat daar de
      // eenheidsmatrix (`overgang.rs`). Alleen zo meet dit de overgang en niet
      // het kaderen. De look-velden blijven nul — de samenstel-pas draait de
      // passthrough-look, de echte look is hierna een rekenpas.
      const eenheid = { schaalX: 1, schaalY: 1, schuifX: 0, schuifY: 0 };
      device.queue.writeBuffer(
        uniformBuffer,
        0,
        schrijfUniforms(
          {
            kaderA: eenheid,
            kaderB: eenheid,
            pasA: inpassing?.pasA ?? eenheid,
            pasB: inpassing?.pasB ?? eenheid,
            meng: m.meng,
            overgang: m.soort,
            vulmodusA: inpassing?.vulmodusA ?? 0,
            vulmodusB: inpassing?.vulmodusB ?? 0,
            tijd: m.tijd,
            frame: m.frame,
            seed: m.seed,
            canvasVerhouding: breedte / hoogte,
            looksterkte: 0,
            afwerking: [],
          },
          velden,
        ),
      );
      const groep = device.createBindGroup({
        layout: samenstelPijp.getBindGroupLayout(0),
        entries: [
          { binding: 0, resource: { buffer: uniformBuffer } },
          { binding: 1, resource: sampler },
          { binding: 2, resource: texA.createView() },
          { binding: 3, resource: texB.createView() },
        ],
      });
      const codeur = device.createCommandEncoder();
      const samen = codeur.beginRenderPass({
        colorAttachments: [
          {
            view: composiet!.createView(),
            clearValue: { r: 0, g: 0, b: 0, a: 1 },
            loadOp: "clear",
            storeOp: "store",
          },
        ],
      });
      samen.setPipeline(samenstelPijp);
      samen.setBindGroup(0, groep);
      samen.draw(4);
      samen.end();
      const eind = keten(codeur, composiet!.createView(), k);
      device.queue.submit([codeur.finish()]);
      const uit = await lees(werk[eind]);
      texA.destroy();
      texB.destroy();
      return uit;
    },
    sluit() {
      plek[0].tex?.destroy();
      plek[1].tex?.destroy();
      leeg.destroy();
      composiet?.destroy();
      for (const t of werk) t.destroy();
      uitlees?.destroy();
      device.destroy();
    },
  };
}

export { GEEN_AFWERKING };
