import type { LegalDocuments } from "./types.ts";

/** Política de privacidade e termos de utilização, em português de Portugal
(#1417). A translation of `en.ts`, machine-drafted and awaiting a native
reader. */
export const LEGAL_PT: LegalDocuments = {
  locale: "pt",
  privacy: {
    title: "Política de privacidade",
    intro: [
      "Esta política explica o que o Sketchy guarda sobre ti, porquê, durante " +
        "quanto tempo e o que podes fazer em relação a isso. O Sketchy é " +
        "gratuito: não mostra publicidade, e nada sobre ti é vendido ou usado " +
        "para te vender o que quer que seja.",
    ],
    sections: [
      {
        id: "operator",
        heading: "Quem é responsável",
        body: [
          "O Sketchy é gerido pelo seu operador, sediado na Suíça, que decide o " +
            "que é guardado e porquê. Podes escrever ao operador para {contact}.",
          "A tudo o que aqui se descreve aplica-se a lei suíça de proteção de " +
            "dados e, quando jogas a partir da União Europeia, também o " +
            "Regulamento Geral sobre a Proteção de Dados da UE.",
        ],
      },
      {
        id: "data",
        heading: "O que é guardado",
        body: ["Apenas o que o jogo precisa para funcionar, ser justo e continuar seguro:"],
        items: [
          "O nome com que jogas, e o nome de utilizador de uma conta.",
          "Se criares uma conta: o teu endereço de email, a tua palavra-passe – " +
            "guardada apenas como um hash de sentido único, a partir do qual não " +
            "pode ser recuperada – e as chaves de acesso ou a autenticação de " +
            "dois fatores que configurares.",
          "As tuas definições e o teu perfil: os teus idiomas e preferências, " +
            "uma fotografia de perfil se carregares uma, os teus amigos, os " +
            "jogadores que bloqueias, as definições de sala guardadas e as " +
            "listas que marcas com estrela.",
          "Os teus jogos: as salas em que jogaste, os teus palpites, pontos e " +
            "resultados, as tuas reações e os desenhos que fizeste.",
          "O chat, nas salas e no átrio.",
          "As listas de palavras que escreves, e se as publicaste.",
          "As denúncias que envias e as denúncias sobre ti, com as mensagens e " +
            "os desenhos a que se referem, e qualquer advertência ou suspensão " +
            "da tua conta.",
          "Um registo de segurança e moderação das ações sensíveis – por " +
            "exemplo as alterações de palavra-passe e de email, bloquear alguém, " +
            "mudar a tua imagem e as decisões da moderação.",
          "Os teus inícios de sessão: uma descrição aproximada de cada " +
            "dispositivo (como «Firefox no Windows»), quando foi usado pela " +
            "última vez e um hash com chave secreta do endereço de rede de onde " +
            "veio. O mesmo tipo de hash fica no registo acima e limita quantas " +
            "vezes algo pode ser feito a partir de um mesmo endereço. O Sketchy " +
            "nunca guarda o próprio endereço, embora os fornecedores que " +
            "transportam o seu tráfego o vejam.",
          "Quando entras e sais das salas, para que os problemas possam ser " +
            "rastreados.",
          "Os relatórios de erros que envias, com uma captura de ecrã se " +
            "anexares uma.",
          "Informação técnica sobre a tua ligação e os erros do teu navegador, " +
            "para encontrar e corrigir problemas. Não contém nenhuma das tuas " +
            "mensagens nem dos teus desenhos.",
        ],
      },
      {
        id: "purposes",
        heading: "Porque é guardado",
        body: [
          "Para fazer funcionar o jogo que queres jogar: salas, turnos, pontos, " +
            "o teu histórico e a tua conta. É o acordo entre ti e o operador, tal " +
            "como descrito nos termos de utilização. O teu endereço de email só " +
            "serve a tua conta: para a confirmar, para repor a palavra-passe e " +
            "para te avisar de alterações e decisões que lhe digam respeito.",
          "Para manter o jogo justo e seguro: moderar denúncias, travar a " +
            "batota, o spam e os abusos, e proteger as contas. É o interesse " +
            "legítimo do operador e de todos os que jogam.",
          "Para encontrar e corrigir problemas, pela mesma razão.",
          "Para responder às autoridades quando a lei obriga o operador a fazê-lo.",
          "Nada sobre ti é usado para publicidade, vendido ou usado para criar " +
            "um perfil teu, e nenhuma decisão com efeitos jurídicos ou " +
            "igualmente significativos para ti é tomada apenas por uma máquina.",
        ],
      },
      {
        id: "visibility",
        heading: "O que os outros jogadores veem",
        body: [
          "Quem está numa sala contigo vê o teu nome, as tuas mensagens, os teus " +
            "desenhos e a tua pontuação.",
          "Os desenhos feitos numa sala pública aparecem na Galeria, onde " +
            "qualquer pessoa os pode ver, com o nome com que foram desenhados: " +
            "jogar numa sala pública é jogar em público, nos termos de " +
            "utilização. Os desenhos de uma sala privada só são vistos por quem " +
            "lá estava. Eliminar a tua conta apaga todos os teus desenhos, exceto " +
            "uma cópia anexada a uma denúncia, que fica com ela; para retirar " +
            "apenas um, escreve para {contact}.",
          "Uma lista de palavras que publiques pode ser lida por todos, com o " +
            "teu nome como autor. O teu perfil mostra o que escolheres mostrar.",
        ],
      },
      {
        id: "recipients",
        heading: "Quem mais os trata",
        body: [
          "Ninguém recebe os teus dados para os usar para fins próprios. O " +
            "operador recorre a alguns fornecedores para fazer funcionar o " +
            "Sketchy – alojamento, entrega pela rede e email – que só os tratam " +
            "segundo as instruções do operador. Quando algum o faz fora da Suíça " +
            "e da UE, é com garantias que a lei reconhece, como as cláusulas " +
            "contratuais-tipo da Comissão Europeia; escreve para {contact} para " +
            "saberes que países e que garantias.",
          "Os moderadores e administradores nomeados pelo operador veem as " +
            "denúncias sobre as quais decidem e aquilo a que se referem. Os " +
            "administradores também leem os relatórios de erros e podem " +
            "consultar uma conta e a sua atividade recente quando algo corre mal.",
          "Os dados só são entregues às autoridades quando a lei o exige.",
        ],
      },
      {
        id: "retention",
        heading: "Durante quanto tempo é guardado",
        body: [],
        items: [
          "Chat: 30 dias, exceto as linhas citadas numa denúncia, que ficam com " +
            "ela.",
          "As denúncias e o que citam, as advertências, as suspensões, o " +
            "registo de segurança e moderação e os relatórios de erros: " +
            "guardados como registo duradouro da moderação e da segurança do " +
            "serviço, mesmo depois de eliminares a tua conta. As entradas do " +
            "registo deixam então de te identificar.",
          "Capturas de ecrã dos relatórios de erros: até o relatório ser " +
            "tratado, e nunca mais de 90 dias.",
          "Convidados: eliminados após 30 dias sem um jogo terminado, ou após " +
            "365 dias sem jogar depois de terem um.",
          "Contas: até as eliminares. Amizades, bloqueios, listas de palavras, " +
            "definições de sala guardadas e estrelas: até os removeres ou " +
            "eliminares a tua conta.",
          "Inícios de sessão: até expirarem, e 30 dias depois.",
          "Entradas e saídas das salas: 30 dias.",
          "Emails enviados para ti: 30 dias.",
          "Exportações de dados que pedires: 7 dias.",
          "Os jogos terminados – pontos, desenhos, reações – fazem parte do " +
            "histórico de todos os que jogaram, por isso são guardados. Se " +
            "eliminares a tua conta, os teus desenhos são apagados e o teu lugar " +
            "nesses jogos é anonimizado, o que mantém intacto o histórico dos " +
            "outros, sem ti.",
        ],
      },
      {
        id: "rights",
        heading: "Os teus direitos",
        body: [
          "Nas Definições podes descarregar uma cópia dos teus dados, corrigir o " +
            "teu nome, email e perfil, e eliminar a tua conta ou a tua " +
            "identidade de convidado, sempre que quiseres.",
          "Tens também o direito de obter tudo o que é guardado sobre ti e de " +
            "saber como é usado – incluindo o que a cópia descarregada não " +
            "contém, como as denúncias sobre ti –, de o fazer corrigir ou " +
            "apagar, de o receber num formato que possas levar para outro lado, " +
            "de te opores ao seu uso para os interesses legítimos do operador e " +
            "de pedir que o seu uso seja limitado. Escreve para {contact} para " +
            "tudo o que as Definições não fazem.",
          "Se achares que os teus dados são mal tratados, podes apresentar " +
            "queixa a uma autoridade de proteção de dados: na Suíça, o " +
            "Comissário Federal para a Proteção de Dados e a Transparência " +
            "(FDPIC/EDÖB), e na UE, a autoridade do país onde vives.",
        ],
      },
      {
        id: "cookies",
        heading: "Cookies e armazenamento",
        body: [
          "O Sketchy usa um único cookie, que mantém a tua sessão iniciada. É " +
            "necessário para o jogo funcionar, por isso não te é pedido que o " +
            "aceites. As tuas definições também ficam guardadas no armazenamento " +
            "do teu próprio navegador.",
          "Não há cookies de publicidade nem de análise, nem scripts de " +
            "terceiros.",
        ],
      },
      {
        id: "age",
        heading: "Idade",
        body: [
          "O Sketchy destina-se a pessoas com {age} anos ou mais. Se és pai, mãe " +
            "ou encarregado de educação e achas que o teu filho ou filha com " +
            "menos de {age} anos está a jogar, escreve para {contact} e os seus " +
            "dados serão apagados.",
        ],
      },
      {
        id: "changes",
        heading: "Alterações a esta política",
        body: [
          "Se esta política mudar, a nova versão é publicada aqui. Uma alteração " +
            "que afete a forma como os teus dados são usados não se aplicará ao " +
            "que foi guardado antes sem te avisar primeiro.",
        ],
      },
    ],
  },
  terms: {
    title: "Termos de utilização",
    intro: [
      "Estes termos são o acordo entre ti e o operador do Sketchy. Ao jogar, " +
        "aceita-los; se não os aceitares, não uses o Sketchy.",
    ],
    sections: [
      {
        id: "agreement",
        heading: "O Sketchy está em beta",
        body: [
          "O Sketchy é gratuito e ainda está a ser construído: as funcionalidades " +
            "mudam, há coisas que avariam e, em casos raros, algo pode perder-se. " +
            "Obrigado por jogares mesmo assim.",
        ],
      },
      {
        id: "age",
        heading: "Quem pode jogar",
        body: ["Tens de ter pelo menos {age} anos. Ao jogar, confirmas que os tens."],
      },
      {
        id: "accounts",
        heading: "O teu nome e a tua conta",
        body: [
          "Escolhe um nome que não se faça passar por outra pessoa nem viole as " +
            "regras. Guarda a tua palavra-passe e o teu início de sessão para ti: " +
            "és responsável pelo que é feito com a tua conta.",
          "Um convidado vive num navegador. Apagar os dados desse navegador faz " +
            "perder o convidado, a não ser que o tenhas transformado numa conta.",
        ],
      },
      {
        id: "fair-play",
        heading: "Jogar limpo",
        body: [
          "Segue as regras. Não faças batota – nada de palpites automáticos, de " +
            "dizer a resposta aos outros ou de jogar como várias pessoas para " +
            "ganhar vantagem –, não tentes partir nem sobrecarregar o Sketchy e " +
            "não o uses para nada ilegal.",
        ],
      },
      {
        id: "content",
        heading: "O que desenhas e escreves",
        body: [
          "O que desenhas, escreves e publicas continua a ser teu. Para que o " +
            "jogo funcione, autorizas o operador a guardá-lo, mostrá-lo e " +
            "copiá-lo dentro do Sketchy – na tua sala, na Galeria para as salas " +
            "públicas, nas listas de palavras que publicas e nas cópias que " +
            "outros fazem delas –, gratuitamente, em todo o mundo e enquanto o " +
            "Sketchy o guardar.",
          "Desenha e escreve apenas o que tens o direito de partilhar, e nada " +
            "que as regras proíbam.",
        ],
      },
      {
        id: "moderation",
        heading: "Moderação",
        body: [
          "Os moderadores podem ocultar conteúdo, advertir jogadores e suspender " +
            "contas que violem estes termos ou as regras. Quando um moderador " +
            "regista a que regra se refere uma decisão, é-te dito. Os dados de " +
            "uma conta suspensa podem continuar a ser descarregados ou " +
            "eliminados, a partir de um dispositivo que tinha sessão iniciada " +
            "quando a suspensão começou ou escrevendo para {contact}.",
        ],
      },
      {
        id: "availability",
        heading: "Sem garantias",
        body: [
          "O Sketchy é fornecido tal como está, sem qualquer garantia de que " +
            "esteja sempre disponível, funcione sem erros ou guarde para sempre o " +
            "que fizeste. O operador pode alterá-lo, pausá-lo ou encerrá-lo.",
        ],
      },
      {
        id: "liability",
        heading: "Responsabilidade",
        body: [
          "Na medida em que a lei o permita, o operador não responde por danos " +
            "indiretos nem pela perda de conteúdos ou dados. Nada aqui limita a " +
            "responsabilidade que a lei não permite limitar, como em caso de dolo " +
            "ou negligência grave.",
        ],
      },
      {
        id: "leaving",
        heading: "Sair",
        body: [
          "Podes parar quando quiseres e eliminar a tua conta nas Definições. O " +
            "operador pode terminar o teu acesso se violares estes termos ou as " +
            "regras, ou encerrar o Sketchy por completo.",
        ],
      },
      {
        id: "law",
        heading: "Que lei se aplica",
        body: [
          "Estes termos regem-se pelo direito suíço, que não te retira a " +
            "proteção que, como consumidor, te dá a lei imperativa do país onde " +
            "vives. Os litígios cabem aos tribunais da sede do operador na " +
            "Suíça, a não ser que essa lei te dê o direito de recorrer aos " +
            "tribunais do teu país.",
        ],
      },
      {
        id: "changes",
        heading: "Alterações a estes termos",
        body: [
          "Se estes termos mudarem num ponto importante, serás avisado antes de " +
            "a alteração se aplicar, e continuar a jogar depois significa que a " +
            "aceitas. As perguntas vão para {contact}.",
        ],
      },
    ],
  },
};
