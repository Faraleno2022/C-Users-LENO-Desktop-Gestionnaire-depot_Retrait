const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, LevelFormat, TabStopType, TabStopPosition,
  TableOfContents, HeadingLevel, BorderStyle, WidthType, ShadingType,
  PageNumber, PageBreak,
} = require("docx");

const ACCENT = "1F4E79";
const LIGHT = "D9E2F3";
const GREY = "595959";

// Helpers ------------------------------------------------------------------
function h1(text) {
  return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(text)] });
}
function h2(text) {
  return new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(text)] });
}
function p(text, opts = {}) {
  return new Paragraph({
    spacing: { after: 120 },
    children: [new TextRun({ text, ...opts })],
  });
}
function bullet(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "puces", level },
    spacing: { after: 60 },
    children: parseRuns(text),
  });
}
function step(text) {
  return new Paragraph({
    numbering: { reference: "etapes", level: 0 },
    spacing: { after: 60 },
    children: parseRuns(text),
  });
}
// Parse **bold** segments inside a string into TextRuns.
function parseRuns(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g).filter((s) => s !== "");
  return parts.map((seg) => {
    if (seg.startsWith("**") && seg.endsWith("**")) {
      return new TextRun({ text: seg.slice(2, -2), bold: true });
    }
    return new TextRun(seg);
  });
}
function note(text) {
  return new Paragraph({
    spacing: { before: 80, after: 160 },
    shading: { fill: "FFF2CC", type: ShadingType.CLEAR },
    border: {
      left: { style: BorderStyle.SINGLE, size: 18, color: "BF9000", space: 8 },
    },
    children: [new TextRun({ text: "Note : ", bold: true }), ...parseRuns(text)],
  });
}

// Simple 2-column table (label / description)
function infoTable(rows, headers = ["Élément", "Description"], widths = [3000, 6360]) {
  const border = { style: BorderStyle.SINGLE, size: 1, color: "BBBBBB" };
  const borders = { top: border, bottom: border, left: border, right: border };
  const total = widths[0] + widths[1];
  const headerRow = new TableRow({
    tableHeader: true,
    children: headers.map((htxt, i) =>
      new TableCell({
        borders,
        width: { size: widths[i], type: WidthType.DXA },
        shading: { fill: ACCENT, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        children: [new Paragraph({ children: [new TextRun({ text: htxt, bold: true, color: "FFFFFF" })] })],
      })
    ),
  });
  const bodyRows = rows.map((r, idx) =>
    new TableRow({
      children: r.map((cell, i) =>
        new TableCell({
          borders,
          width: { size: widths[i], type: WidthType.DXA },
          shading: { fill: idx % 2 === 0 ? "FFFFFF" : "F2F5FB", type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ children: parseRuns(cell) })],
        })
      ),
    })
  );
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: widths,
    rows: [headerRow, ...bodyRows],
  });
}

// Document ------------------------------------------------------------------
const children = [];

// Cover page
children.push(
  new Paragraph({ spacing: { before: 2600, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "Gestionnaire Dépôt / Retrait", bold: true, size: 56, color: ACCENT })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 0 },
    children: [new TextRun({ text: "Guide d'utilisation", size: 36, color: GREY })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 600 },
    children: [new TextRun({ text: "Application de gestion des dépôts, retraits, produits et clients", italics: true, size: 24, color: GREY })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 2400 },
    children: [new TextRun({ text: "Version 1.0", size: 22, color: GREY })] }),
  new Paragraph({ children: [new PageBreak()] }),
);

// Table of contents
children.push(
  new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Sommaire")] }),
  new TableOfContents("Sommaire", { hyperlink: true, headingStyleRange: "1-2" }),
  new Paragraph({ children: [new PageBreak()] }),
);

// 1. Introduction
children.push(h1("1. Présentation"));
children.push(p("Le Gestionnaire Dépôt / Retrait est une application de bureau qui permet de suivre les dépôts et retraits d'argent par client (identifié par un matricule), de gérer un stock de produits et leurs ventes, de produire des rapports et de sauvegarder les données. Une synchronisation en ligne facultative permet d'envoyer les données vers un serveur central."));
children.push(h2("Principales fonctions"));
children.push(bullet("**Dépôt / Retrait** : enregistrement des opérations et calcul automatique du solde de chaque client."));
children.push(bullet("**Produits & Stock** : catalogue de produits, entrées/sorties de stock et alertes de seuil."));
children.push(bullet("**Vente de produits** : vente décomptée sur le solde du client, avec mise à jour du stock."));
children.push(bullet("**Clients** : fiche par matricule (nom, téléphone, solde, historique des opérations)."));
children.push(bullet("**Rapports** : journaliers, mensuels et annuels, exportables en PDF et Excel."));
children.push(bullet("**Sauvegardes** : manuelles et automatiques (planifiées)."));
children.push(bullet("**Synchronisation en ligne** : envoi des données vers un serveur (facultatif)."));

// 2. Installation et démarrage
children.push(h1("2. Installation et démarrage"));
children.push(h2("Pré-requis"));
children.push(bullet("Un ordinateur Windows."));
children.push(bullet("Python 3.10 ou plus récent (si l'application est lancée depuis les sources)."));
children.push(h2("Lancer l'application"));
children.push(step("Ouvrez le dossier de l'application."));
children.push(step("Si nécessaire, installez les dépendances : **pip install -r requirements.txt**."));
children.push(step("Lancez l'application : **python main.py**."));
children.push(note("Au tout premier démarrage, la base de données et le compte administrateur par défaut sont créés automatiquement."));

// 3. Connexion et rôles
children.push(h1("3. Connexion et rôles"));
children.push(h2("Première connexion"));
children.push(p("Un compte super-administrateur est créé automatiquement :"));
children.push(infoTable([
  ["Identifiant", "**admin**"],
  ["Mot de passe", "**admin123**"],
], ["Champ", "Valeur"], [3000, 6360]));
children.push(note("Pour des raisons de sécurité, changez ce mot de passe par défaut dès la première connexion (menu Administrateurs ou Utilisateurs)."));
children.push(h2("Les rôles et leurs droits"));
children.push(infoTable([
  ["Caissier", "Saisie des dépôts/retraits, ventes, consultation des clients et rapports."],
  ["Superviseur", "Comme le caissier, avec un suivi élargi."],
  ["Administrateur", "Gestion des utilisateurs, des produits, de l'administration et des sauvegardes."],
  ["Super administrateur", "Tous les droits, dont la gestion des administrateurs et la restauration."],
], ["Rôle", "Droits principaux"], [3000, 6360]));

// 4. Tableau de bord
children.push(h1("4. Tableau de bord"));
children.push(p("À la connexion, le tableau de bord présente une vue d'ensemble : solde global, totaux des dépôts et retraits, valeur du stock, produits en alerte de stock et ventes du jour. Il se met à jour automatiquement après chaque opération."));

// 5. Dépôt / Retrait
children.push(h1("5. Dépôt et retrait"));
children.push(p("Le menu Dépôt / Retrait permet d'enregistrer les opérations sur le compte d'un client."));
children.push(h2("Enregistrer un dépôt"));
children.push(step("Ouvrez le menu **Dépôt / Retrait**."));
children.push(step("Saisissez le **matricule** du client (et son téléphone si souhaité)."));
children.push(step("Choisissez le type **Dépôt**."));
children.push(step("Saisissez le **montant**, puis validez."));
children.push(p("Le nouveau solde du client est affiché et enregistré."));
children.push(h2("Enregistrer un retrait"));
children.push(step("Saisissez le matricule du client."));
children.push(step("Choisissez le type **Retrait** et le montant."));
children.push(step("Validez. Le retrait n'est accepté que si le solde est suffisant."));
children.push(note("Un retrait supérieur au solde disponible est automatiquement refusé : le solde ne peut jamais devenir négatif."));

// 6. Produits et stock
children.push(h1("6. Produits et stock"));
children.push(h2("Créer un produit"));
children.push(step("Ouvrez le menu **Produits & Stock**."));
children.push(step("Cliquez sur **+ Nouveau produit**."));
children.push(step("Renseignez le nom, le prix unitaire, et éventuellement la référence, la description, la quantité initiale et le seuil d'alerte."));
children.push(step("Enregistrez."));
children.push(h2("Gérer le stock"));
children.push(bullet("**Entrée stock** : ajoute une quantité (réapprovisionnement)."));
children.push(bullet("**Sortie stock** : retire une quantité (casse, perte, etc.)."));
children.push(bullet("L'onglet **Mouvements de stock** trace toutes les entrées et sorties."));
children.push(note("Lorsque le stock d'un produit passe sous son seuil d'alerte, la ligne est mise en évidence et le produit apparaît dans les alertes du tableau de bord."));

// 7. Vente de produits
children.push(h1("7. Vente de produits"));
children.push(p("Une vente déduit le montant du solde du client et diminue le stock du produit."));
children.push(step("Ouvrez le menu **Vente produit**."));
children.push(step("Choisissez le **produit** dans la liste (le stock et le prix s'affichent)."));
children.push(step("Saisissez le **matricule** du client : son solde s'affiche."));
children.push(step("Indiquez la **quantité** : le total à payer se calcule automatiquement."));
children.push(step("Validez. Un reçu peut être imprimé."));
children.push(note("La vente est refusée si le stock est insuffisant ou si le solde du client ne couvre pas le montant. Un administrateur peut annuler une vente : le stock et le solde sont alors restitués."));

// 8. Clients
children.push(h1("8. Gestion des clients"));
children.push(p("Le menu Clients regroupe tous les matricules connus de l'application. Chaque client peut recevoir une fiche détaillée."));
children.push(h2("Liste des clients"));
children.push(p("La liste affiche, pour chaque matricule : le nom, le téléphone, le solde courant, le nombre d'opérations et si une fiche est enregistrée. Une zone de recherche permet de filtrer par matricule ou par nom."));
children.push(bullet("Une ligne **en rouge** signale un client dont le solde est négatif (cas exceptionnel)."));
children.push(bullet("Une ligne **en jaune** signale un matricule connu (via ses opérations) qui n'a pas encore de fiche enregistrée."));
children.push(h2("Créer ou modifier une fiche"));
children.push(step("Cliquez sur **+ Nouvelle fiche** (ou sélectionnez un client puis **Modifier la fiche**)."));
children.push(step("Renseignez le matricule, le nom, le téléphone et une note éventuelle."));
children.push(step("Enregistrez."));
children.push(h2("Consulter l'historique"));
children.push(p("Sélectionnez un client puis cliquez sur **Voir l'historique** (ou double-cliquez sur la ligne). La fiche affiche le solde actuel et la liste chronologique des dépôts, retraits et achats, avec le solde après chaque opération."));

// 9. Rapports
children.push(h1("9. Rapports et exports"));
children.push(step("Ouvrez le menu **Rapports**."));
children.push(step("Choisissez le **jeu de données** : Transactions, Ventes ou État du stock."));
children.push(step("Choisissez la **période** (journalière, mensuelle, annuelle) et les dates."));
children.push(step("Générez le rapport au format **PDF** ou **Excel**."));
children.push(p("Le fichier est enregistré dans le dossier des exports et peut être ouvert ou imprimé."));

// 10. Sauvegardes
children.push(h1("10. Sauvegardes"));
children.push(p("Les sauvegardes protègent vos données contre les pertes accidentelles. Elles sont accessibles dans le menu Administration (réservé aux administrateurs)."));
children.push(h2("Sauvegarde manuelle"));
children.push(step("Ouvrez le menu **Administration**."));
children.push(step("Cliquez sur **Créer une sauvegarde maintenant**."));
children.push(p("La sauvegarde apparaît dans la liste avec sa date, sa taille et son emplacement."));
children.push(h2("Sauvegarde automatique (planifiée)"));
children.push(p("L'application peut créer une sauvegarde automatiquement au démarrage, selon une périodicité que vous définissez."));
children.push(step("Dans le menu **Administration**, section **Sauvegardes**, cochez **Sauvegarde automatique au démarrage**."));
children.push(step("Réglez la périodicité (par ex. tous les **1 jour**) et le nombre de sauvegardes à **conserver**."));
children.push(step("Cliquez sur **Enregistrer**."));
children.push(p("Au prochain démarrage, si le délai est écoulé, une sauvegarde est créée automatiquement ; les plus anciennes sont supprimées au-delà du nombre conservé."));
children.push(h2("Restauration"));
children.push(p("Un super-administrateur peut restaurer une sauvegarde via **Restaurer depuis un fichier**. Une sauvegarde de sécurité de l'état actuel est créée avant toute restauration."));
children.push(note("Les opérations sensibles (restauration, réinitialisation) demandent une confirmation et créent une sauvegarde préalable pour éviter toute perte de données."));

// 11. Synchronisation en ligne
children.push(h1("11. Synchronisation en ligne (facultatif)"));
children.push(p("La synchronisation envoie les données de ce poste vers un serveur central. Elle est à sens unique : le poste envoie ses données, rien n'est rapatrié, et les mots de passe ne sont jamais transmis."));
children.push(h2("Configurer le poste"));
children.push(step("Obtenez l'**URL du serveur** et le **jeton du poste** auprès de l'administrateur du serveur."));
children.push(step("Ouvrez **Administration → Synchronisation en ligne**."));
children.push(step("Renseignez l'URL, le jeton et un nom de poste, puis **Enregistrez la configuration**."));
children.push(step("Cliquez sur **Tester la connexion** pour vérifier, puis **Synchroniser maintenant** pour envoyer les données en attente."));
children.push(p("L'indicateur en haut de la fenêtre indique l'état de la synchronisation et le nombre d'enregistrements restant à envoyer."));
children.push(note("La mise en place du serveur est décrite dans le document technique DEPLOYMENT.md (déploiement sur Render)."));

// 12. Sécurité
children.push(h1("12. Sécurité et bonnes pratiques"));
children.push(bullet("Changez le mot de passe **admin** par défaut dès la première connexion."));
children.push(bullet("Créez un compte nominatif par utilisateur plutôt que de partager un compte."));
children.push(bullet("Les mots de passe sont chiffrés et ne sont jamais envoyés au serveur."));
children.push(bullet("Activez la sauvegarde automatique pour limiter les risques de perte de données."));
children.push(bullet("Les opérations sensibles demandent une confirmation explicite."));
children.push(bullet("Chaque action importante est tracée dans le journal d'audit (consultable par les administrateurs)."));

// 13. Aide rapide
children.push(h1("13. Problèmes fréquents"));
children.push(infoTable([
  ["Retrait refusé", "Le solde du client est insuffisant. Vérifiez le solde dans la fiche client."],
  ["Vente refusée", "Stock insuffisant ou solde du client trop bas pour le montant de l'achat."],
  ["Connexion serveur impossible", "Vérifiez l'URL et le jeton ; le serveur gratuit peut mettre ~30 s à se réveiller."],
  ["Mot de passe oublié", "Un administrateur peut réinitialiser le mot de passe d'un utilisateur."],
], ["Situation", "Que faire"], [3000, 6360]));

// Build doc -----------------------------------------------------------------
const doc = new Document({
  creator: "Gestionnaire Dépôt / Retrait",
  title: "Guide d'utilisation",
  styles: {
    default: { document: { run: { font: "Calibri", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, color: ACCENT, font: "Calibri" },
        paragraph: { spacing: { before: 320, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, color: "2E5496", font: "Calibri" },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 1 } },
    ],
  },
  numbering: {
    config: [
      { reference: "puces",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
          { level: 1, format: LevelFormat.BULLET, text: "◦", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 1440, hanging: 360 } } } },
        ] },
      { reference: "etapes",
        levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
        ] },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      },
    },
    headers: {
      default: new Header({ children: [new Paragraph({
        alignment: AlignmentType.RIGHT,
        border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: ACCENT, space: 4 } },
        children: [new TextRun({ text: "Gestionnaire Dépôt / Retrait — Guide d'utilisation", size: 16, color: GREY })],
      })] }),
    },
    footers: {
      default: new Footer({ children: [new Paragraph({
        tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
        border: { top: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC", space: 4 } },
        children: [
          new TextRun({ text: "Version 1.0", size: 16, color: GREY }),
          new TextRun({ text: "\tPage ", size: 16, color: GREY }),
          new TextRun({ children: [PageNumber.CURRENT], size: 16, color: GREY }),
          new TextRun({ text: " / ", size: 16, color: GREY }),
          new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, color: GREY }),
        ],
      })] }),
    },
    children,
  }],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync("Guide_utilisation.docx", buffer);
  console.log("Guide_utilisation.docx généré (" + buffer.length + " octets)");
});
