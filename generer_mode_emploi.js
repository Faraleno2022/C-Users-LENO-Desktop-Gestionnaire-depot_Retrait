const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, LevelFormat, BorderStyle, WidthType, ShadingType, ImageRun,
} = require("docx");

const BLEU = "0C447C";
const OR = "B07A0B";
const GRIS = "5F5E5A";

function etape(num, titre, lignes) {
  const out = [
    new Paragraph({
      spacing: { before: 140, after: 40 },
      children: [
        new TextRun({ text: `${num}  `, bold: true, color: "FFFFFF", size: 20 }),
        new TextRun({ text: titre, bold: true, color: BLEU, size: 22 }),
      ],
      shading: { fill: "E6F1FB", type: ShadingType.CLEAR },
    }),
  ];
  for (const l of lignes) {
    out.push(new Paragraph({
      numbering: { reference: "puces", level: 0 },
      spacing: { after: 20 },
      children: l,
    }));
  }
  return out;
}

const monospace = (t) => new TextRun({ text: t, font: "Consolas", size: 18, color: "1F2937" });
const txt = (t, o = {}) => new TextRun({ text: t, size: 20, ...o });

const jsonBloc = new Table({
  width: { size: 9020, type: WidthType.DXA },
  columnWidths: [9020],
  rows: [new TableRow({ children: [new TableCell({
    width: { size: 9020, type: WidthType.DXA },
    shading: { fill: "F1EFE8", type: ShadingType.CLEAR },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: "D3D1C7" },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: "D3D1C7" },
      left: { style: BorderStyle.SINGLE, size: 4, color: "D3D1C7" },
      right: { style: BorderStyle.SINGLE, size: 4, color: "D3D1C7" },
    },
    margins: { top: 80, bottom: 80, left: 160, right: 160 },
    children: [
      new Paragraph({ children: [monospace("{")] }),
      new Paragraph({ children: [monospace('  "enabled": true,')] }),
      new Paragraph({ children: [monospace('  "url": "https://gestionnaire-depot-retrait.onrender.com",')] }),
      new Paragraph({ children: [monospace('  "token": "LE-JETON-DU-POSTE",')] }),
      new Paragraph({ children: [monospace('  "interval_seconds": 5')] }),
      new Paragraph({ children: [monospace("}")] }),
    ],
  })] })],
});

function encadre(fill, bordure, titre, contenu) {
  return new Table({
    width: { size: 9020, type: WidthType.DXA },
    columnWidths: [9020],
    rows: [new TableRow({ children: [new TableCell({
      width: { size: 9020, type: WidthType.DXA },
      shading: { fill, type: ShadingType.CLEAR },
      borders: {
        top: { style: BorderStyle.SINGLE, size: 4, color: bordure },
        bottom: { style: BorderStyle.SINGLE, size: 4, color: bordure },
        left: { style: BorderStyle.SINGLE, size: 18, color: bordure },
        right: { style: BorderStyle.SINGLE, size: 4, color: bordure },
      },
      margins: { top: 80, bottom: 80, left: 160, right: 160 },
      children: [
        new Paragraph({ spacing: { after: 20 }, children: [new TextRun({ text: titre, bold: true, size: 20, color: bordure })] }),
        ...contenu.map((runs) => new Paragraph({ spacing: { after: 0 }, children: runs })),
      ],
    })] })],
  });
}

const doc = new Document({
  styles: { default: { document: { run: { font: "Arial", size: 20 } } } },
  numbering: {
    config: [{
      reference: "puces",
      levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 460, hanging: 240 } } } }],
    }],
  },
  sections: [{
    properties: { page: {
      size: { width: 11906, height: 16838 },
      margin: { top: 850, right: 1000, bottom: 700, left: 1000 },
    } },
    children: [
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 40 },
        children: [new ImageRun({
          type: "png",
          data: fs.readFileSync("assets/logo_emab.png"),
          transformation: { width: 150, height: 84 },
          altText: { title: "EMAB GROUP", description: "Logo EMAB GROUP", name: "logo" },
        })],
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 30 },
        children: [new TextRun({ text: "Installation d’un poste — Console Web", bold: true, size: 30, color: BLEU })],
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 120 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: BLEU, space: 6 } },
        children: [new TextRun({ text: "Chaque poste partage automatiquement les mêmes données via le serveur en ligne.", italics: true, size: 18, color: GRIS })],
      }),

      ...etape("1", "Créer le jeton du poste (sur un poste déjà connecté)", [
        [txt("Ouvrir "), monospace("…onrender.com/postes/"), txt("  →  menu Administration › Postes & jetons")],
        [txt('Nom du poste : '), txt("Console-poste-2", { bold: true }), txt('  →  cliquer '), txt("Créer le poste", { bold: true }), txt("  →  copier le jeton")],
      ]),

      ...etape("2", "Installer le logiciel sur la nouvelle machine", [
        [txt("Lancer "), txt("EMAB-Console-Web-Setup-1.0.0.exe", { bold: true }), txt(" (clé USB) → Suivant")],
        [txt("Garder coché « Démarrer automatiquement avec Windows »")],
      ]),

      ...etape("3", "Lancer une fois, puis fermer", [
        [txt("Ouvrir le raccourci "), txt("EMAB Console Web", { bold: true }), txt(", attendre l’ouverture du navigateur, puis fermer la console (raccourci "), txt("Arrêter EMAB Console", { bold: true }), txt(")")],
      ]),

      ...etape("4", "Configurer la synchronisation", [
        [txt("Windows + R, coller : "), monospace('notepad "%LOCALAPPDATA%\\EMAB GROUP\\ConsoleWeb\\render_sync.json"')],
        [txt("Remplacer le contenu par (coller le jeton de l’étape 1), puis Enregistrer (Ctrl+S) :")],
      ]),
      jsonBloc,

      ...etape("5", "Repartir d’une base vierge", [
        [txt("Windows + R, coller : "), monospace("%LOCALAPPDATA%\\EMAB GROUP\\ConsoleWeb")],
        [txt("Supprimer le fichier "), txt("console.sqlite3", { bold: true }), txt(" (et "), monospace("-wal / -shm"), txt(" s’ils existent)")],
      ]),

      ...etape("6", "Relancer et se connecter", [
        [txt("Relancer "), txt("EMAB Console Web", { bold: true }), txt("  →  « Synchronisation initiale… » récupère toutes les données")],
        [txt("Ouvrir "), monospace("http://127.0.0.1:8765"), txt("  →  se connecter avec les identifiants de l’entreprise")],
      ]),

      new Paragraph({ spacing: { after: 60 }, children: [] }),

      encadre("E1F5EE", "0F6E56", "✔  Règle d’or", [
        [txt("Laisser la console ouverte (elle démarre seule avec Windows). PC allumé + internet = données à jour sur tous les postes en ~10 secondes.", { size: 19 })],
      ]),

      new Paragraph({ spacing: { after: 40 }, children: [] }),

      encadre("FAEEDA", OR, "⚠  À ne pas faire", [
        [txt("Ne pas faire deux retraits sur le MÊME client depuis deux postes en même temps (risque de double-débit). Un client = une caisse à la fois. Les dépôts, eux, sont toujours sûrs.", { size: 19 })],
      ]),

      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 160 },
        children: [new TextRun({ text: "EMAB GROUP — Assistance : ______________________", size: 16, color: GRIS })],
      }),
    ],
  }],
});

Packer.toBuffer(doc).then((buffer) => {
  const out = require("path").join(require("os").homedir(), "Desktop", "EMAB - Mode emploi installation poste.docx");
  fs.writeFileSync(out, buffer);
  console.log("DOCX cree : " + out);
});
