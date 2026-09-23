"""Testes do aplicativo de janela (Tkinter).

Não abrem janela visível: a raiz é criada e escondida com `withdraw()`. O laço
de eventos é bombeado à mão com `update()` para não travar o pytest.

Usa o vídeo mudo de propósito: o pipeline roda inteiro sem precisar carregar
nenhum modelo de transcrição, então o teste é rápido e não depende de download.
"""

from __future__ import annotations

import time
import types
from pathlib import Path

import pytest
from conftest import ffmpeg_required

tkinter = pytest.importorskip("tkinter", reason="Tkinter não disponível neste Python")


@pytest.fixture(scope="session")
def tk_root():
    """Uma única raiz Tcl para toda a sessão.

    Criar e destruir vários `Tk()` no mesmo processo corrompe o interpretador
    Tcl ("invalid command name tcl_findLibrary"), então cada teste ganha uma
    Toplevel filha em vez de uma raiz nova.
    """
    try:
        root = tkinter.Tk()
    except tkinter.TclError as exc:  # pragma: no cover - sem ambiente gráfico
        pytest.skip(f"sem servidor gráfico: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture()
def app(tk_root, tmp_path: Path, monkeypatch):
    """Cria o aplicativo com a janela escondida e o encerra ao final."""
    from lauda import desktop, theme

    # A preferência de tema não pode vazar para o perfil real do usuário.
    monkeypatch.setattr(theme, "PREFS_PATH", tmp_path / "ui.json")

    window = tkinter.Toplevel(tk_root)
    window.withdraw()
    instance = desktop.LaudaApp(window)
    instance.folder_var.set(str(tmp_path))
    # Teste não pode abrir janela do Explorador na máquina de quem roda a suíte.
    instance.var_open_folder.set(False)
    try:
        yield instance
    finally:
        instance.shutdown()
        window.destroy()


def _drenar(app, ciclos: int = 12) -> None:
    """Roda o laço só o bastante para a fila chegar aos widgets.

    Diferente do `_pump`, não espera worker nenhum: serve para o que a própria
    janela põe na fila, como as linhas do registro.
    """
    for _ in range(ciclos):
        app.root.update()
        time.sleep(0.02)


def _pump(app, seconds: float = 120.0) -> None:
    """Roda o laço de eventos até o worker terminar (ou estourar o tempo)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.root.update()
        if app.worker is not None and not app.worker.is_alive():
            for _ in range(20):  # deixa a fila de progresso ser drenada
                app.root.update()
                time.sleep(0.02)
            return
        time.sleep(0.02)
    raise AssertionError("o processamento não terminou no tempo esperado")


def test_janela_abre_com_o_passo_a_passo(app):
    assert app.root.title().startswith("Lauda Local")
    ajuda = app.text_help.get("1.0", "end-1c")
    assert "COMO USAR" in ajuda
    assert "1." in ajuda and "4." in ajuda
    # Os botões de resultado só liberam depois de processar.
    assert str(app.button_open["state"]) == "disabled"


def test_pasta_de_saida_ja_vem_preenchida(app, tmp_path: Path):
    assert app.folder_var.get() == str(tmp_path)


def test_processar_sem_arquivo_avisa_e_nao_roda(app, monkeypatch):
    avisos: list[str] = []
    monkeypatch.setattr(
        "lauda.desktop.messagebox.showwarning",
        lambda title, message: avisos.append(message),
    )
    app.start()
    assert avisos and "Escolha primeiro um arquivo" in avisos[0]
    assert app.worker is None


def test_selecao_de_modelo_e_idioma_viram_valores_reais(app):
    from lauda.desktop import LANGUAGES, MODEL_LABELS

    app.language_var.set("Português")
    app.model_var.set("Rascunho — bem rápido (tiny)")
    assert app._selected(app.language_var, LANGUAGES) == "pt"
    assert app._selected(app.model_var, MODEL_LABELS) == "tiny"


@ffmpeg_required
def test_processa_e_mostra_a_previa_na_janela(app, silent_video: Path, tmp_path: Path):
    """Fluxo completo: escolher arquivo, processar, ver o relatório na aba."""
    app.input_path = silent_video
    app.start()
    _pump(app)

    assert app.result is not None, "o resultado não chegou à interface"

    previa = app.text_report.get("1.0", "end-1c")
    assert "LAUDA LOCAL" in previa, "o relatório não foi carregado na prévia"
    assert "1. IDENTIDADE DO ARQUIVO" in previa
    assert silent_video.name in previa

    arquivos = app.text_files.get("1.0", "end-1c")
    assert "ARQUIVOS GERADOS" in arquivos
    assert "report.txt" in arquivos

    # Os arquivos existem mesmo, na pasta escolhida no passo 2.
    gerado = tmp_path / f"{silent_video.stem}.report.txt"
    assert gerado.exists()

    for button in (app.button_folder, app.button_open, app.button_copy):
        assert str(button["state"]) == "normal", "botões de resultado continuaram travados"

    assert app.progress["value"] == 100


@ffmpeg_required
def test_erro_do_pipeline_vira_mensagem_amigavel(app, invalid_file: Path, monkeypatch):
    erros: list[str] = []
    monkeypatch.setattr(
        "lauda.desktop.messagebox.showerror",
        lambda title, message: erros.append(message),
    )
    app.input_path = invalid_file
    app.start()
    _pump(app, seconds=60.0)

    assert erros, "o erro não chegou ao usuário"
    assert "não conseguiu ler" in erros[0]
    # A janela volta a ficar utilizável.
    assert str(app.go_button["state"]) == "normal"


# --------------------------------------------------------------------------- #
# Tema
# --------------------------------------------------------------------------- #
def test_alterna_para_o_modo_escuro(app):
    from lauda.theme import DARK, LIGHT

    app.set_theme("claro")
    assert app.theme is LIGHT
    assert app.theme_button["text"] == "Modo escuro"

    app.toggle_theme()
    assert app.theme is DARK
    assert app.theme_choice == "escuro"
    assert app.theme_button["text"] == "Modo claro", "o botão precisa oferecer a volta"


def test_o_modo_escuro_repinta_a_previa(app):
    from lauda.theme import DARK, LIGHT

    app.set_theme("claro")
    claro = app.text_report.cget("background")

    app.set_theme("escuro")
    escuro = app.text_report.cget("background")

    assert claro.lower() == LIGHT.preview_bg.lower()
    assert escuro.lower() == DARK.preview_bg.lower()
    assert app.text_report.cget("foreground").lower() == DARK.preview_fg.lower()
    # Todas as abas, não só a que estava visível.
    for widget in app._texts:
        assert widget.cget("background").lower() == DARK.preview_bg.lower()


def test_a_escolha_de_tema_fica_guardada(app, tmp_path: Path):
    from lauda.theme import load_choice

    app.set_theme("escuro")
    assert load_choice() == "escuro"
    assert (tmp_path / "ui.json").exists()


def test_tema_invalido_e_recusado(app):
    with pytest.raises(ValueError):
        app.set_theme("roxo")


def test_troca_de_tema_nao_apaga_o_relatorio(app, silent_video: Path):
    """Repintar não pode limpar o que já está na tela."""
    conteudo = "== RELATORIO DE TESTE =="
    app._set_text(app.text_report, conteudo)
    app.set_theme("escuro")
    assert app.text_report.get("1.0", "end-1c") == conteudo
    assert str(app.text_report["state"]) == "disabled", "a prévia continua só de leitura"


# --------------------------------------------------------------------------- #
# Limites de uso (os sliders)
# --------------------------------------------------------------------------- #
def test_sliders_comecam_no_padrao(app):
    from lauda.limits import DEFAULT

    assert app.limits == DEFAULT
    assert app.limit_vars["cpu_percent"].get() == DEFAULT.cpu_percent
    assert app.limit_value_labels["cpu_percent"]["text"] == "100%"


def test_slider_arredonda_para_multiplos_de_cinco(app):
    app._on_slider("cpu_percent", "37.4")
    assert app.limit_vars["cpu_percent"].get() == 35
    assert app.limits.cpu_percent == 35
    assert app.limit_value_labels["cpu_percent"]["text"] == "35%"


def test_o_cursor_acompanha_o_arredondamento(app):
    """O desenho e o número precisam concordar."""
    app._on_slider("cpu_percent", "37.4")
    assert app.limit_scales["cpu_percent"].get() == pytest.approx(35, abs=0.01)


def test_gpu_em_zero_mostra_desligada(app):
    app._on_slider("gpu_percent", "0")
    assert app.limit_value_labels["gpu_percent"]["text"] == "desligada"
    assert app.limits.use_gpu is False


def test_slider_respeita_o_minimo(app):
    """CPU não pode ir a zero: o app ficaria inutilizável."""
    app._on_slider("cpu_percent", "0")
    assert app.limit_vars["cpu_percent"].get() == 10


def test_limites_ficam_salvos_no_perfil(app):
    from lauda.limits import load

    app._on_slider("ram_percent", "30")
    assert load().ram_percent == 30


def test_voltar_ao_padrao(app):
    from lauda.limits import DEFAULT

    app._on_slider("cpu_percent", "20")
    app._on_slider("gpu_percent", "0")
    assert app.limits != DEFAULT

    app.reset_limits()
    assert app.limits == DEFAULT
    assert app.limit_value_labels["gpu_percent"]["text"] == "100%"


def test_resumo_explica_o_efeito(app):
    app._on_slider("gpu_percent", "0")
    texto = app.limits_summary["text"]
    assert "GPU desligada" in texto
    assert "rodaria em cpu" in texto, "o resumo precisa dizer onde vai rodar"


def test_os_limites_chegam_ao_processamento(app, silent_video: Path, monkeypatch):
    """O slider só vale se o valor realmente atravessar até o job."""
    capturado: dict = {}

    def fake_run(options, progress=None, on_event=None, cancel=None, **kwargs):
        capturado["limits"] = options.limits
        raise LaudaErrorForTest("parando aqui de propósito")

    from lauda import runner

    class LaudaErrorForTest(Exception):
        pass

    monkeypatch.setattr(runner, "run_with_recovery", fake_run)
    monkeypatch.setattr(
        "lauda.desktop.messagebox.showerror", lambda title, message: None
    )

    app._on_slider("cpu_percent", "40")
    app._on_slider("gpu_percent", "0")
    app.input_path = silent_video
    app.start()
    _pump(app, seconds=30.0)

    assert capturado["limits"].cpu_percent == 40
    assert capturado["limits"].use_gpu is False


def test_aviso_de_recuperacao_aparece_no_status(app):
    app._on_recovery("travou", "O processamento parou de responder.")
    assert "parou de responder" in app.status_label["text"]
    assert app.recovery_messages == ["O processamento parou de responder."]


# --------------------------------------------------------------------------- #
# Modo rápido
# --------------------------------------------------------------------------- #
def test_modo_rapido_comeca_desligado(app):
    assert app.var_fast.get() is False


def test_o_resumo_diz_o_modo(app):
    assert "sequencial" in app.limits_summary["text"]
    app.var_fast.set(True)
    app._refresh_limits_summary()
    assert "em lotes" in app.limits_summary["text"]


def test_o_modo_rapido_chega_ao_processamento(app, silent_video, monkeypatch):
    from lauda import runner
    from lauda.desktop import BATCH_SIZE

    capturado: dict = {}

    def fake_run(options, progress=None, on_event=None, cancel=None, **kwargs):
        capturado["batch_size"] = options.batch_size
        raise RuntimeError("parando aqui")

    monkeypatch.setattr(runner, "run_with_recovery", fake_run)
    monkeypatch.setattr(
        "lauda.desktop.messagebox.showerror", lambda title, message: None
    )

    app.var_fast.set(True)
    app.input_path = silent_video
    app.start()
    _pump(app, seconds=30.0)

    assert capturado["batch_size"] == BATCH_SIZE


def test_a_janela_volta_se_tiver_sido_minimizada(app, monkeypatch):
    """O usuário sai, o Windows minimiza, ele volta — o resultado tem de estar lá."""
    chamadas: list[str] = []
    monkeypatch.setattr(app.root, "wm_state", lambda: "iconic")
    monkeypatch.setattr(app.root, "deiconify", lambda: chamadas.append("deiconify"))

    app._restore_if_minimized()
    assert chamadas == ["deiconify"]


def test_janela_normal_nao_e_mexida(app, monkeypatch):
    chamadas: list[str] = []
    monkeypatch.setattr(app.root, "wm_state", lambda: "normal")
    monkeypatch.setattr(app.root, "deiconify", lambda: chamadas.append("deiconify"))

    app._restore_if_minimized()
    assert chamadas == [], "não devemos mexer numa janela que está visível"


def _clique(widget, x: int = 8, y: int = 8) -> None:
    """Dispara o tratador de clique do widget.

    A janela dos testes fica escondida (`withdraw`), e o Tk não entrega eventos
    de mouse a widgets não mapeados. Então checamos que o vínculo existe e
    chamamos o tratador com um evento montado à mão.
    """
    evento = tkinter.Event()
    evento.x, evento.y = x, y
    if hasattr(widget, "_toggle"):                      # ToggleSwitch
        assert "<Button-1>" in widget.bind()
        widget._toggle(evento)
    elif hasattr(widget, "_on_release"):                # RoundedButton
        assert "<Button-1>" in widget.bind()
        # O botão só dispara se a soltura cair dentro dele — e, com a janela
        # escondida, "dentro" é 1x1. O clique tem de respeitar essa caixa.
        evento.x = min(x, widget.winfo_width())
        evento.y = min(y, widget.winfo_height())
        widget._on_press(evento)
        widget._on_release(evento)
    else:                                               # RoundedScrollbar
        assert "<Button-1>" in widget.bind()
        widget._press(evento)


def _com_tamanho(widget, width: int, height: int, monkeypatch) -> None:
    """Finge a geometria: numa janela escondida o Tk devolve 1x1."""
    monkeypatch.setattr(widget, "winfo_width", lambda: width)
    monkeypatch.setattr(widget, "winfo_height", lambda: height)


def test_o_interruptor_liga_e_desliga_no_clique(app):
    """O interruptor é desenhado no Canvas: o clique tem de continuar valendo."""
    from lauda.widgets import ToggleSwitch

    switch = next(s for s in app._switches if s._variable is app.var_srt)
    assert isinstance(switch, ToggleSwitch)

    assert app.var_srt.get() is False
    _clique(switch)
    assert app.var_srt.get() is True, "clicar tem de ligar"
    _clique(switch)
    assert app.var_srt.get() is False, "clicar de novo tem de desligar"


def test_o_interruptor_acompanha_a_variavel(app, monkeypatch):
    """Ligar por código (ex.: perfil salvo) tem de repintar o interruptor."""
    switch = next(s for s in app._switches if s._variable is app.var_diarize)
    _com_tamanho(switch, 300, 34, monkeypatch)

    app.var_diarize.set(True)
    app.root.update_idletasks()
    switch.redraw()
    assert switch.find_all(), "o interruptor ligado tem de estar desenhado"


def test_a_barra_de_rolagem_some_quando_tudo_cabe(app, monkeypatch):
    """Sem conteúdo para rolar não há cursor desenhado — a barra fica limpa."""
    barra = app._scrollbars[0]
    _com_tamanho(barra, 10, 300, monkeypatch)

    barra.set(0.0, 1.0)
    assert barra.find_all() == (), "tudo visível: nada a desenhar"

    barra.set(0.0, 0.25)
    assert barra.find_all() != (), "com conteúdo maior que a tela o cursor aparece"


def test_a_barra_de_rolagem_pede_moveto_ao_arrastar(app, monkeypatch):
    """Ela substitui a ttk.Scrollbar: tem de falar o mesmo protocolo do Tk."""
    from lauda.widgets import RoundedScrollbar

    pedidos: list[tuple] = []
    barra = RoundedScrollbar(
        app.root, orient="vertical", command=lambda *args: pedidos.append(args)
    )
    _com_tamanho(barra, 10, 200, monkeypatch)
    barra.set(0.0, 0.5)

    _clique(barra, x=5, y=180)
    assert pedidos, "o clique na trilha tem de mover a visão"
    acao, fracao = pedidos[-1]
    assert acao == "moveto"
    assert 0.0 <= fracao <= 0.5, "não pode passar do fim do conteúdo"
    barra.destroy()


def test_nenhum_widget_retangular_do_ttk_sobrou(app):
    """Guarda o visual arredondado: quem voltar ao ttk quebra este teste."""
    import tkinter.ttk as ttk

    def varrer(widget):
        yield widget
        for filho in widget.winfo_children():
            yield from varrer(filho)

    proibidos = (ttk.Checkbutton, ttk.Scrollbar, ttk.Notebook, ttk.Scale, ttk.Progressbar)
    encontrados = [w for w in varrer(app.root) if isinstance(w, proibidos)]
    assert encontrados == [], f"widgets quadrados do ttk na tela: {encontrados}"


# --------------------------------------------------------------------------- #
# Tela nova: barra lateral, zona de soltar e trilha de etapas
# --------------------------------------------------------------------------- #
def test_a_barra_lateral_troca_de_pagina(app):
    """Clicar num item da lateral mostra a página dele e esconde as outras."""
    app.nav.select(app.tab_limits)
    assert app.tab_limits.winfo_manager() == "pack"
    assert app.tab_job.winfo_manager() == "", "a página anterior tem de sair"

    app.nav.select(app.tab_job)
    assert app.tab_job.winfo_manager() == "pack"


def test_a_tela_abre_na_pagina_do_trabalho(app):
    assert app.nav.select() == str(app.tab_job)


def test_o_arquivo_escolhido_aparece_no_cartao(app, silent_video: Path):
    app._accept_file(silent_video)

    assert app.input_path == silent_video
    assert app.file_label.cget("text") == silent_video.name
    assert app.file_meta.cget("text"), "o cartão mostra tamanho e duração"
    assert app.file_row.winfo_manager() == "grid", "a linha do arquivo tem de aparecer"


def test_tirar_o_arquivo_volta_ao_estado_inicial(app, silent_video: Path):
    app._accept_file(silent_video)
    app.clear_file()

    assert app.input_path is None
    assert app.file_row.winfo_manager() == "", "a linha do arquivo tem de sumir"
    assert app.stepper.current == 0


def test_soltar_um_arquivo_equivale_a_escolher(app, silent_video: Path):
    """O caminho chega do gerenciador de janelas como lista do Tcl."""
    # É assim que o gerenciador de janelas manda o caminho: entre chaves.
    evento = types.SimpleNamespace(data="{" + str(silent_video) + "}")
    app._on_drop(evento)

    assert app.input_path == silent_video


def test_soltar_uma_pasta_avisa_em_vez_de_aceitar(app, tmp_path: Path, monkeypatch):
    avisos: list[str] = []
    monkeypatch.setattr(
        "lauda.desktop.messagebox.showwarning",
        lambda title, message: avisos.append(message),
    )
    evento = types.SimpleNamespace(data="{" + str(tmp_path) + "}")
    app._on_drop(evento)

    assert app.input_path is None
    assert avisos, "soltar algo que não é arquivo tem de avisar"


def test_a_trilha_de_etapas_acompanha_o_processamento(app):
    from lauda.desktop import PIPELINE_STEPS, Progress

    app._on_progress(Progress(stage="extract", fraction=0.2, message=""))
    assert app.stepper.current == 1, "extrair áudio é pré-processamento"

    app._on_progress(Progress(stage="asr", fraction=0.5, message=""))
    assert app.stepper.current == 2

    app._on_progress(Progress(stage="render", fraction=0.9, message=""))
    assert app.stepper.current == 4
    assert app.stepper.current < len(PIPELINE_STEPS), "só conclui quando terminar"


def test_o_estado_na_lateral_segue_o_progresso(app):
    from lauda.desktop import Progress

    app._on_progress(Progress(stage="asr", fraction=0.42, message=""))
    assert "Transcrevendo" in app.state_label.cget("text")
    assert "42" in app.state_label.cget("text")


def test_erro_pinta_o_estado_de_vermelho(app, monkeypatch):
    monkeypatch.setattr(
        "lauda.desktop.messagebox.showerror", lambda title, message: None
    )
    app._on_error("deu ruim")

    assert app.state_label.cget("text") == "Erro"
    assert app._state_color == app.theme.danger


# --------------------------------------------------------------------------- #
# Diagnóstico da máquina na abertura
# --------------------------------------------------------------------------- #
def _check(level: str = "ruim"):
    """Uma avaliação de mentira, para não depender do hardware da máquina de teste."""
    from lauda.hardware import Finding, MachineCheck

    return MachineCheck(
        level=level,
        headline="Esta máquina provavelmente não vai dar conta.",
        findings=[
            Finding("Processador", "2 threads", "apertada", "Poucos núcleos."),
            Finding("Memória (RAM)", "3,4 GB", level, "Abaixo de 4 GB."),
            Finding("ffmpeg", "instalado", "boa"),
        ],
        advice=["Na página Desempenho existem controles de processador e memória."],
    )


def test_maquina_boa_nao_abre_dialogo(app):
    app._on_machine(_check("boa"))

    assert app._machine_dialog is None
    assert app.machine is not None
    assert app.machine.level == "boa"


def test_maquina_ruim_abre_o_dialogo(app):
    app._on_machine(_check("ruim"))

    assert app._machine_dialog is not None, "máquina ruim tem de avisar"
    app._machine_dialog.destroy()
    app._machine_dialog = None


def test_o_veredito_aparece_na_pagina_desempenho(app):
    app._on_machine(_check("ruim"))
    app._machine_dialog.destroy()
    app._machine_dialog = None

    texto = app.machine_label.cget("text")
    assert "não vai dar conta" in texto
    assert "Processador: 2 threads" in texto


def test_quem_pediu_para_nao_avisar_nao_e_incomodado(app, tmp_path: Path, monkeypatch):
    from lauda import theme

    monkeypatch.setattr(theme, "PREFS_PATH", tmp_path / "ui.json")
    theme.save_flag("skip_machine_warning", True)

    app._on_machine(_check("ruim"))
    assert app._machine_dialog is None


def test_continuar_fecha_so_o_dialogo(app):
    saiu: list[str] = []
    app._on_close = lambda: saiu.append("fechou")  # type: ignore[method-assign]

    app._on_machine(_check("ruim"))
    janela = app._machine_dialog
    botao = _botao_por_texto(janela, "Continuar mesmo assim")
    _clique(botao, x=5, y=5)

    assert saiu == [], "continuar não pode encerrar o aplicativo"
    assert app._machine_dialog is None


def test_fechar_o_aplicativo_encerra(app):
    saiu: list[str] = []
    app._on_close = lambda: saiu.append("fechou")  # type: ignore[method-assign]

    app._on_machine(_check("ruim"))
    botao = _botao_por_texto(app._machine_dialog, "Fechar o aplicativo")
    _clique(botao, x=5, y=5)

    assert saiu == ["fechou"]


def test_a_escolha_de_nao_avisar_fica_salva(app, tmp_path: Path, monkeypatch):
    from lauda import theme

    monkeypatch.setattr(theme, "PREFS_PATH", tmp_path / "ui.json")
    app._on_close = lambda: None  # type: ignore[method-assign]

    app._on_machine(_check("ruim"))
    app.var_skip_warning.set(True)
    _clique(_botao_por_texto(app._machine_dialog, "Continuar mesmo assim"), x=5, y=5)

    assert theme.load_flag("skip_machine_warning") is True


def test_o_dialogo_da_pagina_desempenho_nao_oferece_fechar(app):
    app.machine = _check("apertada")
    janela = app.show_machine_dialog()

    assert _botao_por_texto(janela, "Fechar o aplicativo") is None
    assert _botao_por_texto(janela, "Entendi") is not None
    janela.destroy()
    app._machine_dialog = None


def test_sem_avaliacao_nao_ha_dialogo(app):
    assert app.machine is None
    assert app.show_machine_dialog() is None


def _botao_por_texto(janela, texto: str):
    """Acha um RoundedButton pelo rótulo, varrendo a árvore da janela."""
    from lauda.widgets import RoundedButton

    def varrer(widget):
        yield widget
        for filho in widget.winfo_children():
            yield from varrer(filho)

    for widget in varrer(janela):
        if isinstance(widget, RoundedButton) and widget.cget("text") == texto:
            return widget
    return None


def test_a_nuvem_vem_do_png_e_ganha_a_cor_do_tema(app):
    """O arquivo entra como forma; a cor tem de sair sempre do tema."""
    from lauda.widgets import CLOUD_PNG, tinted_icon

    assert CLOUD_PNG.exists(), "o ícone precisa viajar junto com o pacote"
    escuro = tinted_icon(str(CLOUD_PNG), 74, app.theme.accent)
    assert escuro is not None and escuro.width() == 74

    outra_cor = tinted_icon(str(CLOUD_PNG), 74, "#B3261E")
    assert outra_cor is not escuro, "cada cor gera a sua imagem"
    assert tinted_icon(str(CLOUD_PNG), 74, app.theme.accent) is escuro, "e o cache guarda"


def test_arquivo_de_icone_ausente_nao_derruba_a_tela(app):
    from lauda.widgets import tinted_icon

    assert tinted_icon("C:/nao/existe.png", 32, "#000000") is None


def test_a_zona_de_soltar_desenha_a_nuvem(app, monkeypatch):
    _com_tamanho(app.drop, 520, 420, monkeypatch)
    app.drop.redraw()

    imagens = [
        item for item in app.drop.find_all() if app.drop.type(item) == "image"
    ]
    assert imagens, "a nuvem tem de estar desenhada na zona de soltar"


# --------------------------------------------------------------------------- #
# Preferências da tela de trabalho (BACKLOG-016)
# --------------------------------------------------------------------------- #
def test_as_escolhas_da_tela_vao_para_o_disco(app):
    from lauda.theme import load_value

    app.language_var.set("Português")
    app.var_diarize.set(True)
    app.var_srt.set(True)
    app.folder_var.set(r"D:\meus videos")
    app._save_prefs()

    guardado = load_value("job", {})
    assert guardado["language"] == "Português"
    assert guardado["diarize"] is True
    assert guardado["srt"] is True
    assert guardado["output_dir"] == r"D:\meus videos"


def test_a_proxima_abertura_encontra_as_mesmas_escolhas(app, tk_root, tmp_path: Path):
    """É o teste que importa: fechar e abrir tem de devolver a mesma tela."""
    from lauda import desktop

    app.model_var.set("Máxima qualidade — lento (large-v3)")
    app.var_vtt.set(True)
    app.var_fast.set(True)
    app._save_prefs()

    janela = tkinter.Toplevel(tk_root)
    janela.withdraw()
    outra = desktop.LaudaApp(janela)
    try:
        assert outra.model_var.get() == "Máxima qualidade — lento (large-v3)"
        assert outra.var_vtt.get() is True
        assert outra.var_fast.get() is True
    finally:
        outra.shutdown()
        janela.destroy()


def test_valor_que_nao_existe_mais_volta_ao_padrao(app, tk_root):
    """Se um rótulo sumir entre versões, o combobox não pode mostrar fantasma."""
    from lauda import desktop
    from lauda.theme import save_value

    save_value("job", {"quality": "Modelo que foi removido", "language": "Klingon"})

    janela = tkinter.Toplevel(tk_root)
    janela.withdraw()
    outra = desktop.LaudaApp(janela)
    try:
        assert outra.model_var.get() in [rotulo for rotulo, _ in desktop.MODEL_LABELS]
        assert outra.language_var.get() in [rotulo for rotulo, _ in desktop.LANGUAGES]
    finally:
        outra.shutdown()
        janela.destroy()


def test_perfil_corrompido_nao_impede_a_abertura(app, tk_root):
    from lauda import desktop
    from lauda.theme import save_value

    save_value("job", "isto deveria ser um dicionário")

    janela = tkinter.Toplevel(tk_root)
    janela.withdraw()
    outra = desktop.LaudaApp(janela)
    try:
        assert outra.var_srt.get() is False, "sem preferências válidas, valem os padrões"
    finally:
        outra.shutdown()
        janela.destroy()


def test_mudar_uma_opcao_agenda_a_gravacao(app):
    """A gravação é adiada: digitar um caminho não pode escrever a cada tecla."""
    app._save_prefs()  # zera o agendamento que a montagem da tela deixou
    assert app._prefs_after is None

    app.var_visual.set(True)
    assert app._prefs_after is not None, "a mudança tem de agendar a gravação"


def test_fechar_logo_apos_mudar_nao_perde_a_escolha(app):
    from lauda.theme import load_value

    app.var_words.set(True)
    assert app._prefs_after is not None
    app.shutdown()

    assert load_value("job", {})["words"] is True


# --------------------------------------------------------------------------- #
# Configurações são preferências; o manual mora em Ajuda (BACKLOG-045)
# --------------------------------------------------------------------------- #
def test_o_passo_a_passo_saiu_de_configuracoes(app):
    """Quem abre Configurações quer mudar algo, não ler um tutorial."""

    def textos(widget):
        for filho in widget.winfo_children():
            try:
                rotulo = filho.cget("text")
            except Exception:
                rotulo = ""
            if rotulo:
                yield str(rotulo)
            yield from textos(filho)

    em_configuracoes = " ".join(textos(app.tab_settings))
    assert "Como usar" not in em_configuracoes
    assert "Opções de processamento" in em_configuracoes


def test_a_ajuda_tem_a_sua_propria_pagina(app):
    app.nav.select(app.tab_help)
    assert app.nav.select() == str(app.tab_help)
    assert "COMO USAR" in app.text_help.get("1.0", "end")


def test_configuracoes_resume_o_que_esta_guardado(app):
    app.var_diarize.set(True)
    app.var_srt.set(True)
    app._save_prefs()

    resumo = app.prefs_summary.cget("text")
    assert "identificar quem fala" in resumo
    assert ".srt" in resumo
    assert "Pasta de saída" in resumo


def test_restaurar_padroes_desliga_tudo(app):
    """Sem caminho de volta, uma opção esquecida ligada vira mistério."""
    from lauda.theme import load_value

    app.var_diarize.set(True)
    app.var_fast.set(True)
    app.model_var.set("Máxima qualidade — lento (large-v3)")

    app.reset_job_prefs()

    assert app.var_diarize.get() is False
    assert app.var_fast.get() is False
    assert app.model_var.get() == "Recomendado — equilibrado (small)"
    assert load_value("job", {})["diarize"] is False
    assert "nenhum" in app.prefs_summary.cget("text")


# --------------------------------------------------------------------------- #
# Registro ao vivo na página Relatório (BACKLOG-017)
# --------------------------------------------------------------------------- #
def test_o_log_do_app_chega_a_tela(app):
    """Sem esperar o fim: o que o app registra aparece na página Relatório."""
    import logging

    app._show_report_view("log")
    logging.getLogger("lauda.teste").info("carregando o modelo")
    _drenar(app)

    assert any("carregando o modelo" in linha for linha in app._log_lines)
    assert "carregando o modelo" in app.text_report.get("1.0", "end")


def test_cada_etapa_vira_uma_linha_so(app):
    """O ASR reporta a cada segmento; o registro não pode repetir a etapa."""
    from lauda.desktop import Progress

    app._show_report_view("log")
    for fracao in (0.30, 0.45, 0.60):
        app._on_progress(Progress(stage="asr", fraction=fracao, message=""))
    _drenar(app)

    transcrevendo = [linha for linha in app._log_lines if "Transcrevendo" in linha]
    assert len(transcrevendo) == 1, f"uma linha por etapa, não por evento: {transcrevendo}"


def test_o_registro_nao_cresce_sem_limite(app):
    from lauda.desktop import LOG_VIEW_LINES

    for indice in range(LOG_VIEW_LINES + 120):
        app._append_log(f"linha {indice}")

    assert len(app._log_lines) == LOG_VIEW_LINES
    assert app._log_lines[-1] == f"linha {LOG_VIEW_LINES + 119}", "guarda as mais novas"


def test_alternar_entre_registro_e_relatorio(app):
    app._append_log("uma linha do registro")
    app._show_report_view("log")
    assert "uma linha do registro" in app.text_report.get("1.0", "end")
    assert app.button_view.cget("text") == "Ver o relatório"

    app.toggle_report_view()
    assert app._report_view == "report"
    assert app.button_view.cget("text") == "Ver o registro"
    assert "uma linha do registro" not in app.text_report.get("1.0", "end")


def test_o_fim_do_trabalho_volta_para_o_laudo(app, silent_video: Path, tmp_path: Path):
    app.input_path = silent_video
    app.folder_var.set(str(tmp_path))
    app.start()
    _pump(app, seconds=90.0)

    assert app.result is not None, "o trabalho precisa terminar para este teste valer"
    assert app._report_view == "report", "ao terminar, a página mostra o laudo"
    assert "RELATÓRIO DE MÍDIA" in app.text_report.get("1.0", "end")
    assert app._log_lines, "e o registro do que aconteceu continua guardado"


def test_o_handler_sai_do_logger_ao_fechar(app, tk_root):
    """Handler esquecido no logger global empurraria linhas para uma fila morta."""
    import logging

    from lauda import desktop

    janela = tkinter.Toplevel(tk_root)
    janela.withdraw()
    outra = desktop.LaudaApp(janela)
    handler = outra.log_handler
    assert handler in logging.getLogger("lauda").handlers

    outra.shutdown()
    janela.destroy()
    assert handler not in logging.getLogger("lauda").handlers


# --------------------------------------------------------------------------- #
# O que acontece quando o trabalho termina (BACKLOG-032)
# --------------------------------------------------------------------------- #
def _resultado_falso(app, tmp_path: Path, com_srt: bool = True):
    """Um JobResult com os arquivos existindo em disco, para o pós-trabalho."""
    from tests_helpers import make_result

    saida = tmp_path / "saida"
    saida.mkdir(exist_ok=True)
    outputs = {"report.txt": str(saida / "video.report.txt")}
    Path(outputs["report.txt"]).write_text("laudo", encoding="utf-8")
    if com_srt:
        for tipo in ("srt", "vtt"):
            caminho = saida / f"video.{tipo}"
            caminho.write_text("1\n00:00:00,000 --> 00:00:01,000\noi\n", encoding="utf-8")
            outputs[tipo] = str(caminho)

    resultado = make_result()
    resultado.outputs = outputs
    return resultado


def test_a_legenda_fica_junto_do_video(app, tmp_path: Path):
    """É a cópia ao lado do arquivo que faz o player achar a legenda sozinho."""
    origem = tmp_path / "filmes"
    origem.mkdir()
    app.input_path = origem / "video.mp4"
    app.input_path.write_bytes(b"nao importa")
    app.var_subs_beside.set(True)

    copiados = app._copy_subtitles_beside_source(_resultado_falso(app, tmp_path))

    assert (origem / "video.srt").exists()
    assert (origem / "video.vtt").exists()
    assert len(copiados) == 2
    assert (tmp_path / "saida" / "video.srt").exists(), "a cópia original continua lá"


def test_origem_sem_permissao_nao_derruba_o_trabalho(app, tmp_path: Path, monkeypatch):
    origem = tmp_path / "somente-leitura"
    origem.mkdir()
    app.input_path = origem / "video.mp4"
    app.input_path.write_bytes(b"nao importa")

    def sem_permissao(*_args, **_kwargs):
        raise OSError("acesso negado")

    monkeypatch.setattr("lauda.desktop.shutil.copy2", sem_permissao)
    assert app._copy_subtitles_beside_source(_resultado_falso(app, tmp_path)) == []


def test_desligado_nao_copia_nada(app, tmp_path: Path):
    origem = tmp_path / "filmes"
    origem.mkdir()
    app.input_path = origem / "video.mp4"
    app.input_path.write_bytes(b"nao importa")
    app.var_subs_beside.set(False)
    app.var_open_folder.set(False)

    app._after_job(_resultado_falso(app, tmp_path))

    assert not (origem / "video.srt").exists()
    assert app._extra_outputs == []


def test_abrir_a_pasta_ao_terminar_respeita_a_escolha(app, tmp_path: Path, monkeypatch):
    abertos: list[Path] = []
    monkeypatch.setattr(app, "_reveal", lambda caminho: abertos.append(caminho))
    app.input_path = tmp_path / "video.mp4"
    app.input_path.write_bytes(b"x")
    app.var_subs_beside.set(False)

    app.var_open_folder.set(False)
    app._after_job(_resultado_falso(app, tmp_path, com_srt=False))
    assert abertos == []

    app.var_open_folder.set(True)
    app._after_job(_resultado_falso(app, tmp_path, com_srt=False))
    assert abertos == [Path(app.folder_var.get())]


def test_as_copias_aparecem_na_lista_de_arquivos(app, tmp_path: Path):
    origem = tmp_path / "filmes"
    origem.mkdir()
    app.input_path = origem / "video.mp4"
    app.input_path.write_bytes(b"x")
    app.var_open_folder.set(False)

    resultado = _resultado_falso(app, tmp_path)
    app._after_job(resultado)
    app._on_done(resultado)

    lista = app.text_files.get("1.0", "end")
    assert "cópia" in lista
    assert str(origem / "video.srt") in lista


# --------------------------------------------------------------------------- #
# Cobertura visível na janela (BACKLOG-015)
# --------------------------------------------------------------------------- #
def test_a_cobertura_aparece_no_resumo(app, tmp_path: Path):
    from lauda.coverage import analyze_coverage
    from lauda.types import SegmentInfo

    resultado = _resultado_falso(app, tmp_path, com_srt=False)
    resultado.segments = [SegmentInfo(id=0, start=0, end=30, text="oi")]
    resultado.coverage = analyze_coverage(resultado.segments, 30.0)
    app.var_open_folder.set(False)
    app._on_done(resultado)

    assert "Cobertura" in app.text_files.get("1.0", "end")
    assert "100.0%" in app.text_files.get("1.0", "end")


def test_cobertura_baixa_vira_aviso_na_tela(app, tmp_path: Path):
    """O texto pode estar certo e ainda faltar metade do arquivo."""
    from lauda.coverage import analyze_coverage
    from lauda.types import SegmentInfo

    resultado = _resultado_falso(app, tmp_path, com_srt=False)
    resultado.segments = [
        SegmentInfo(id=0, start=0, end=10, text="oi"),
        SegmentInfo(id=1, start=80, end=90, text="tchau"),
    ]
    resultado.coverage = analyze_coverage(resultado.segments, 90.0)
    app.var_open_folder.set(False)
    app._on_done(resultado)

    status = app.status_label.cget("text")
    assert "não viraram texto" in status
    # O Tk devolve um objeto Tcl aqui, não uma string Python.
    assert str(app.status_label.cget("foreground")) == app.theme.accent_warm


def test_o_interruptor_do_ollama_explica_o_que_faz(app):
    """A pergunta do QA: "quando eu desligo isso?" tem de estar respondida na tela."""
    def textos(widget):
        for filho in widget.winfo_children():
            try:
                rotulo = filho.cget("text")
            except Exception:
                rotulo = ""
            if rotulo:
                yield str(rotulo)
            yield from textos(filho)

    # O rótulo do interruptor é desenhado no Canvas, não é um `text` de widget.
    rotulos = [switch._text for switch in app._switches]
    assert "Integrar com Ollama" in rotulos

    tela = " ".join(textos(app.tab_job))
    assert "NÃO usa Ollama" in tela, "precisa dizer que a transcrição não depende dele"
    assert "qwen3:14b" in tela, "e qual modelo ele vai querer"


# --------------------------------------------------------------------------- #
# Tempo restante e subtexto da etapa (BACKLOG-019 e 020)
# --------------------------------------------------------------------------- #
def test_duracao_em_linguagem_de_gente():
    from lauda.desktop import _duration_pt

    assert _duration_pt(None) == "—"
    assert _duration_pt(0.2) == "1 s", "nunca prometer zero"
    assert _duration_pt(45) == "45 s"
    assert _duration_pt(150) == "2 min"
    assert _duration_pt(3600) == "1 h"
    assert _duration_pt(4800) == "1 h 20 min"


def test_o_comeco_do_trabalho_nao_chuta_tempo(app):
    """Nos primeiros instantes a conta é dominada por carregar o modelo."""
    import time as _time

    app._job_started = _time.monotonic() - 5
    assert app._estimate_remaining(0.02) is None, "cedo demais para estimar"
    assert app._estimate_remaining(1.0) is None, "acabou, não há o que estimar"


def test_a_estimativa_usa_o_ritmo_medido(app):
    import time as _time

    app._job_started = _time.monotonic() - 30  # 30 s para fazer 25%
    restante = app._estimate_remaining(0.25)

    assert restante is not None
    assert 85 <= restante <= 95, f"90 s é o que falta nesse ritmo, veio {restante}"


def test_o_restante_aparece_no_status_e_na_trilha(app):
    import time as _time

    from lauda.desktop import Progress

    app._job_started = _time.monotonic() - 60
    app._on_progress(Progress(stage="asr", fraction=0.50, message=""))

    assert "faltam" in app.status_label.cget("text")
    assert "faltam" in app.stepper._note
    assert "50%" in app.stepper._note


def test_o_fim_limpa_a_estimativa(app, tmp_path: Path):
    import time as _time

    from lauda.desktop import Progress

    app._job_started = _time.monotonic() - 60
    app._on_progress(Progress(stage="asr", fraction=0.50, message=""))
    assert app.stepper._note

    app.var_open_folder.set(False)
    app._on_done(_resultado_falso(app, tmp_path, com_srt=False))
    assert app.stepper._note == ""
    assert app._eta_seconds is None


# --------------------------------------------------------------------------- #
# Seção do Ollama em Configurações (BACKLOG-027)
# --------------------------------------------------------------------------- #
def test_ollama_fora_do_ar_explica_que_nada_quebra(app):
    app._on_ollama((None, "Ollama não respondeu em http://127.0.0.1:11434 (URLError)."))

    texto = app.ollama_status.cget("text")
    assert "não respondeu" in texto
    assert "funciona igual" in texto, "a ausência do Ollama não pode parecer defeito"
    assert str(app.button_ollama_pull["state"]) == "disabled"


def test_modelo_ausente_libera_o_botao_de_baixar(app):
    app._on_ollama((["mistral:7b"], "ok"))

    assert "nenhum modelo compatível" in app.ollama_status.cget("text")
    assert str(app.button_ollama_pull["state"]) == "normal"


def test_modelo_certo_deixa_o_botao_travado(app):
    from lauda.desktop import DEFAULT_OLLAMA_MODEL

    app._on_ollama(([DEFAULT_OLLAMA_MODEL], "ok"))

    assert "Tudo pronto" in app.ollama_status.cget("text")
    assert str(app.button_ollama_pull["state"]) == "disabled", "não há o que baixar"


def test_o_andamento_do_download_aparece(app):
    app._on_pull((0.42, "downloading — 3,8 / 9,0 GB (42%)"))

    assert app.ollama_progress["value"] == pytest.approx(42.0)
    assert "3,8 / 9,0 GB" in app.ollama_status.cget("text")


def test_download_com_erro_nao_deixa_o_botao_preso(app):
    app._pulling = True
    app._on_pull_done((False, "falha ao baixar 'qwen3:14b': URLError"))

    assert app._pulling is False
    assert str(app.button_ollama_pull["state"]) == "normal", "tem de dar para tentar de novo"
    assert "Não deu certo" in app.ollama_status.cget("text")


# ------------------------------------------------------- fila e histórico --
def test_soltar_varios_arquivos_enfileira_o_resto(app, silent_video: Path, tone_wav: Path):
    evento = types.SimpleNamespace(
        data="{" + str(silent_video) + "} {" + str(tone_wav) + "}"
    )
    app._on_drop(evento)

    assert app.input_path == silent_video, "o primeiro vai para o cartão"
    assert app.pending == [tone_wav], "o resto espera a vez"
    assert app.queue_row.winfo_manager() == "grid"
    assert "1 arquivo" in app.queue_label.cget("text")


def test_um_arquivo_so_nao_mostra_a_fila(app, silent_video: Path):
    app._accept_files([silent_video])

    assert app.pending == []
    assert app.queue_row.winfo_manager() == "", "sem fila, sem linha de fila"


def test_soltar_com_trabalho_rodando_manda_tudo_para_a_fila(
    app, silent_video: Path, tone_wav: Path
):
    app._accept_file(silent_video)
    app.worker = types.SimpleNamespace(is_alive=lambda: True)

    app._accept_files([tone_wav])

    assert app.input_path == silent_video, "o trabalho em curso não é trocado"
    assert app.pending == [tone_wav]
    app.worker = None


def test_esvaziar_a_fila_descarta_quem_nao_comecou(app, silent_video: Path, tone_wav: Path):
    app._accept_files([silent_video, tone_wav])
    app.clear_queue()

    assert app.pending == []
    assert app.input_path == silent_video, "o arquivo do cartão continua"


def test_tirar_o_arquivo_tambem_limpa_a_fila(app, silent_video: Path, tone_wav: Path):
    app._accept_files([silent_video, tone_wav])
    app.clear_file()

    assert app.pending == []
    assert app.queue_row.winfo_manager() == ""


def test_a_fila_chama_o_proximo_ao_terminar(app, silent_video: Path, tone_wav: Path):
    chamadas: list[Path] = []
    app._accept_files([silent_video, tone_wav])
    app.start = lambda: chamadas.append(app.input_path)  # type: ignore[method-assign]

    app._advance_queue()

    assert app.input_path == tone_wav, "o próximo entrou no cartão"
    assert chamadas == [tone_wav], "e começou sozinho"
    assert app.pending == []


def test_arquivo_da_fila_que_sumiu_e_pulado(app, silent_video: Path, tmp_path: Path):
    sumido = tmp_path / "nao_existe.mp4"
    chamadas: list[Path] = []
    app.pending = [sumido, silent_video]
    app.start = lambda: chamadas.append(app.input_path)  # type: ignore[method-assign]

    app._advance_queue()

    assert chamadas == [silent_video], "pula o que não existe e segue"


def test_fila_vazia_nao_comeca_nada(app, silent_video: Path):
    chamadas: list[int] = []
    app.start = lambda: chamadas.append(1)  # type: ignore[method-assign]

    app._advance_queue()

    assert chamadas == []


def test_a_fila_espera_a_thread_anterior_encerrar(app, silent_video: Path):
    chamadas: list[int] = []
    app.start = lambda: chamadas.append(1)  # type: ignore[method-assign]
    app.worker = types.SimpleNamespace(is_alive=lambda: True)

    app._queue_wait = 0
    app._start_next()

    assert chamadas == [], "não pode começar com a anterior viva"
    app.worker = None
    app.root.update()


def test_a_fila_desiste_se_a_anterior_nunca_encerra(app):
    app.worker = types.SimpleNamespace(is_alive=lambda: True)
    app._queue_wait = 41

    app._start_next()

    assert "interrompida" in app.status_label.cget("text")
    app.worker = None


def test_a_pagina_arquivos_comeca_com_o_convite(app):
    conteudo = app.text_files.get("1.0", "end-1c")

    assert "Nenhum trabalho ainda" in conteudo


def test_o_trabalho_terminado_entra_no_historico(app, tmp_path: Path):
    from tests_helpers import make_result

    from lauda import history

    app._on_done(make_result())

    entradas = history.load()
    assert len(entradas) == 1
    assert entradas[0].file_name == "entrada.wav"
    conteudo = app.text_files.get("1.0", "end-1c")
    assert "RESUMO DO PROCESSAMENTO" in conteudo, "o trabalho recém-feito continua no topo"
    assert "HISTÓRICO" in conteudo


def test_o_erro_tambem_entra_no_historico(app, silent_video: Path, monkeypatch):
    from lauda import history

    monkeypatch.setattr("lauda.desktop.messagebox.showerror", lambda *a: None)
    app._accept_file(silent_video)

    app._on_error("ffprobe não encontrado")

    entradas = history.load()
    assert len(entradas) == 1
    assert entradas[0].status == "erro"
    assert entradas[0].detail == "ffprobe não encontrado"


def test_erro_no_meio_da_fila_nao_para_os_outros(
    app, silent_video: Path, tone_wav: Path, monkeypatch
):
    monkeypatch.setattr("lauda.desktop.messagebox.showerror", lambda *a: None)
    chamadas: list[Path] = []
    app._accept_files([silent_video, tone_wav])
    app.start = lambda: chamadas.append(app.input_path)  # type: ignore[method-assign]

    app._on_error("esse arquivo não tem áudio")

    assert chamadas == [tone_wav], "o próximo da fila roda mesmo assim"


def test_limpar_o_historico_esvazia_a_pagina(app, monkeypatch):
    from tests_helpers import make_result

    from lauda import history

    app._on_done(make_result())
    monkeypatch.setattr("lauda.desktop.messagebox.askokcancel", lambda *a: True)

    app.clear_history()

    assert history.load() == []
    conteudo = app.text_files.get("1.0", "end-1c")
    assert "Nenhum trabalho ainda" in conteudo
    assert "RESUMO DO PROCESSAMENTO" not in conteudo


def test_limpar_o_historico_respeita_o_cancelar(app, monkeypatch):
    from tests_helpers import make_result

    from lauda import history

    app._on_done(make_result())
    monkeypatch.setattr("lauda.desktop.messagebox.askokcancel", lambda *a: False)

    app.clear_history()

    assert len(history.load()) == 1, "quem cancelou não perde nada"


def test_abrir_o_laudo_do_historico_avisa_quando_nao_ha(app, monkeypatch):
    avisos: list[str] = []
    monkeypatch.setattr(
        "lauda.desktop.messagebox.showinfo",
        lambda title, message: avisos.append(message),
    )
    app.open_history_report()

    assert avisos, "sem laudo em disco, o usuário precisa saber por quê"


def test_abrir_o_laudo_do_historico_usa_o_mais_recente(app, tmp_path: Path, monkeypatch):
    from lauda import history

    laudo = tmp_path / "laudo.report.txt"
    laudo.write_text("conteúdo", encoding="utf-8")
    history.record(history.HistoryEntry(file_name="a.wav", report_path=str(laudo)))
    abertos: list[Path] = []
    monkeypatch.setattr(app, "_reveal", abertos.append)

    app.open_history_report()

    assert abertos == [laudo]


def test_a_pasta_so_abre_quando_a_fila_acaba(app, tmp_path: Path, monkeypatch):
    from tests_helpers import make_result

    abertos: list[Path] = []
    monkeypatch.setattr(app, "_reveal", abertos.append)
    app.var_open_folder.set(True)
    app.pending = [tmp_path / "proximo.wav"]

    app._after_job(make_result())
    assert abertos == [], "no meio da fila, nada de janela do Explorador"

    app.pending.clear()
    app._after_job(make_result())
    assert abertos == [tmp_path], "no fim, abre uma vez só"


def test_a_fila_inteira_usa_as_escolhas_do_comeco(app, silent_video: Path, tone_wav: Path):
    """Mexer num interruptor no meio da fila não muda quem ainda não começou."""
    opcoes: list[object] = []
    app._accept_files([silent_video, tone_wav])
    app.var_srt.set(True)
    app._work = lambda options: opcoes.append(options)  # type: ignore[method-assign]

    app.start()
    app.worker.join(5)
    app.var_srt.set(False)          # o usuário muda de ideia no meio
    app.var_diarize.set(True)
    app._advance_queue()
    app.worker.join(5)

    assert len(opcoes) == 2
    assert opcoes[0].write_srt is True and opcoes[1].write_srt is True
    assert opcoes[1].diarize is False, "a fila não pega opção nova no meio"


def test_a_rodada_seguinte_le_a_tela_de_novo(app, silent_video: Path):
    opcoes: list[object] = []
    app._accept_file(silent_video)
    app._work = lambda options: opcoes.append(options)  # type: ignore[method-assign]

    app.start()
    app.worker.join(5)
    app._advance_queue()            # fila vazia: solta o congelamento
    app.var_srt.set(True)
    app.start()
    app.worker.join(5)

    assert opcoes[0].write_srt is False
    assert opcoes[1].write_srt is True, "sem fila, a próxima rodada usa a tela atual"


# --------------------------------------------- página Desempenho (028/029) --
def _maquina(app, *, cuda: bool, vram=4.0, ram=16.0, nucleos=16):
    from lauda.hardware import Finding, HardwareInfo, MachineCheck

    hardware = HardwareInfo(
        has_cuda=cuda, cuda_device_count=1 if cuda else 0,
        gpu_name="RTX 3050" if cuda else None, gpu_vram_gb=vram if cuda else None,
        cpu_count=nucleos, ram_gb=ram, platform="teste",
    )
    check = MachineCheck(
        level="ok", headline="Esta máquina dá conta.",
        findings=[
            Finding("Processador", f"{nucleos} threads", "boa"),
            Finding("Memória (RAM)", f"{ram:.1f} GB", "ok"),
            Finding("ffmpeg", "instalado", "boa"),
        ],
        advice=["Comece com arquivos curtos."],
        hardware=hardware,
    )
    app._on_machine(check)
    return check


def test_desempenho_tem_tres_abas(app):
    assert [botao._text for botao, _ in app.perf_tabs._tabs] == [
        "Resumo", "Limites", "Diagnóstico"
    ]


def test_o_preset_muda_os_quatro_controles(app):
    from lauda.limits import preset_by_key

    app.apply_preset("leve")

    leve = preset_by_key("leve")
    assert app.limits == leve.limits
    assert app.limit_vars["cpu_percent"].get() == leve.limits.cpu_percent
    assert app.limit_scales["gpu_percent"].get() == leve.limits.gpu_percent


def test_o_preset_em_vigor_fica_aceso(app):
    app.apply_preset("equilibrado")

    acesos = [k for k, b in app.preset_buttons.items() if b in app._primary_buttons]
    assert acesos == ["equilibrado"]


def test_mexer_no_slider_apaga_os_presets(app):
    app.apply_preset("equilibrado")
    app._on_slider("cpu_percent", "35")

    assert not [k for k, b in app.preset_buttons.items() if b in app._primary_buttons]
    assert "Ajuste manual" in app.preset_blurb.cget("text")


def test_o_resumo_nao_fala_em_porcentagem_de_nucleo(app):
    app.apply_preset("leve")

    assert "1/4 dos núcleos" not in app.preset_blurb.cget("text")
    assert "%" not in app.preset_blurb.cget("text")


def test_com_gpu_o_resumo_avisa_que_a_cpu_fica_parada(app):
    """BACKLOG-029: CPU em 0% durante um trabalho em CUDA não é bug silencioso."""
    _maquina(app, cuda=True)
    app.apply_preset("rapido")

    plano = app.perf_plan.cget("text")
    assert "placa de vídeo" in plano
    assert "quase parado" in plano, "sem isso, o usuário acha que travou"


def test_gpu_em_zero_manda_para_a_cpu_e_a_tela_diz(app):
    _maquina(app, cuda=True)
    app.apply_preset("leve")          # leve = GPU 0%

    plano = app.perf_plan.cget("text")
    assert "no processador" in plano
    assert "desligada nos Limites" in plano


def test_maquina_sem_gpu_explica_o_motivo(app):
    _maquina(app, cuda=False)
    app.apply_preset("rapido")

    assert "Nenhuma placa NVIDIA" in app.perf_plan.cget("text")


def test_limite_abaixo_do_recomendado_vira_aviso(app):
    _maquina(app, cuda=False, ram=8.0, nucleos=4)
    app.model_var.set("Máxima qualidade — lento (large-v3)")
    app.var_diarize.set(True)
    app.apply_preset("leve")          # RAM 40% de 8 GB = 3,2 GB

    texto = app.perf_need.cget("text")
    assert texto.startswith("Atenção")
    assert "rebaixado" in texto
    assert str(app.perf_need.cget("foreground")) == app.theme.accent_warm


def test_limite_folgado_nao_alarma(app):
    _maquina(app, cuda=False, ram=32.0)
    app.model_var.set("Recomendado — equilibrado (small)")
    app.var_diarize.set(False)
    app.apply_preset("rapido")

    texto = app.perf_need.cget("text")
    assert not texto.startswith("Atenção")
    assert "liberam" in texto


def test_trocar_a_qualidade_reavalia_o_que_o_trabalho_pede(app):
    _maquina(app, cuda=False, ram=16.0)
    app.model_var.set("Rascunho — bem rápido (tiny)")
    leve = app.perf_need.cget("text")
    app.model_var.set("Máxima qualidade — lento (large-v3)")
    pesado = app.perf_need.cget("text")

    assert leve != pesado, "mudar a qualidade tem de mudar a conta"


def test_o_ollama_aparece_como_custo_separado(app):
    _maquina(app, cuda=False)
    app.var_summarize.set(True)

    assert "Ollama" in app.perf_need.cget("text")


def test_o_diagnostico_fica_na_tela_sem_dialogo(app):
    _maquina(app, cuda=True)

    linhas = app.diag_rows.winfo_children()
    assert linhas, "o diagnóstico não pode viver só dentro de um diálogo"
    textos = [w.cget("text") for w in linhas]
    assert "Processador" in textos and "ffmpeg" in textos
    assert "Comece com arquivos curtos." in app.diag_advice.cget("text")


def test_o_diagnostico_e_redesenhado_e_nao_acumulado(app):
    _maquina(app, cuda=True)
    antes = len(app.diag_rows.winfo_children())
    _maquina(app, cuda=True)

    assert len(app.diag_rows.winfo_children()) == antes, "redesenhar, não empilhar"


def test_o_modo_escuro_repinta_os_presets(app):
    app.apply_preset("leve")
    app.set_theme("escuro")

    aceso = app.preset_buttons["leve"]
    assert aceso in app._primary_buttons
    assert aceso._fill == app.theme.primary


# --------------------------------------------- tamanho das legendas (034) --
def test_o_tamanho_da_legenda_chega_ao_processamento(app, silent_video: Path):
    opcoes: list[object] = []
    app._accept_file(silent_video)
    app.density_var.set("Legendas curtas (1–2 s)")
    app._work = lambda options: opcoes.append(options)  # type: ignore[method-assign]

    app.start()
    app.worker.join(5)

    assert opcoes[0].subtitle_density == "curta"


def test_o_tamanho_da_legenda_comeca_no_equilibrado(app):
    from lauda.cues import DEFAULT_DENSITY, DENSITY_LABELS

    assert app._selected(app.density_var, DENSITY_LABELS) == DEFAULT_DENSITY


def test_o_tamanho_da_legenda_fica_guardado(app, tmp_path: Path):
    import json

    app.density_var.set("Blocos longos (até 1 min)")
    app._save_prefs()

    salvo = json.loads((tmp_path / "ui.json").read_text(encoding="utf-8"))
    assert salvo["job"]["subtitle_density"] == "Blocos longos (até 1 min)"
