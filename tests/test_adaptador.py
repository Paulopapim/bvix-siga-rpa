"""Parser da resposta executeRule.do no formato observado em 26/11 (dados fictícios)."""

from bvix_siga.siga.playwright_adapter import parse_rule_return, registro_de

CORPO = ("$mainform().document._ruleReturn = ['[{\\\"ordem\\\":1,\\\"idsin\\\":100,\\\"empid\\\":1,"
         "\\\"numerosin\\\":\\\"2026-00001\\\",\\\"nome\\\":\\\"FULANO DE TAL\\\",\\\"cpfcnpj\\\":\\\"012.345.678-90\\\","
         "\\\"placa\\\":\\\"ABC0D12\\\",\\\"veiculo\\\":\\\"CARRO \\\",\\\"tipoeventoid\\\":null,\\\"tipoevento\\\":null}, \\n "
         "{\\\"ordem\\\":2,\\\"idsin\\\":99,\\\"empid\\\":1,\\\"numerosin\\\":\\\"2026-00000\\\",\\\"nome\\\":\\\"EMPRESA LOGÍSTICA\\\","
         "\\\"cpfcnpj\\\":\\\"00.000.000/0001-91\\\",\\\"placa\\\":\\\"XYZ9K88\\\",\\\"veiculo\\\":\\\"VOLVO\\\","
         "\\\"tipoeventoid\\\":2699,\\\"tipoevento\\\":\\\"CONSTATACAO DE DANOS\\\"}]', 'true'];\n$mainform().hideWait();")


def test_parse_rule_return():
    dados = parse_rule_return(CORPO)
    assert len(dados) == 2 and dados[1]["nome"] == "EMPRESA LOGÍSTICA"
    r = registro_de(dados[0])
    assert r.protocolo == "2026-00001" and r.id_interno == "100"
    assert r.cpfcnpj == "012.345.678-90" and r.tipo_evento is None


def test_parse_rule_return_sem_lista():
    assert parse_rule_return("$mainform().hideWait();") is None


def test_cadeia_relatorio_historico_formato_observado():
    import re
    passo1 = ("<script type=\"text/javascript\"> var mainframe = parent.mainframe </script> <script type=\"text/javascript\">"
              " openWFRReportFinal('1', 'openreport.jsp?id=AAAA-BBBB&type=PDF&sys=SIG&name=Hist%C3%B3rico+do+Sinistro', 'PDF', false); </script>")
    passo2 = "<script language=\"JavaScript\"> <!-- window.location = 'WFRReports/Generated/AAAA-BBBB.PDF'; //--> </script>"
    m = re.search(r"openWFRReportFinal\('[^']*',\s*'([^']+)'", passo1)
    assert m.group(1).startswith("openreport.jsp?id=AAAA-BBBB")
    m2 = re.search(r"window\.location\s*=\s*'([^']+\.PDF)'", passo2, re.I)
    assert m2.group(1) == "WFRReports/Generated/AAAA-BBBB.PDF"


def test_url_do_anexo_na_resposta_da_regra():
    import re
    corpo = ("$mainform().document._ruleReturn = 'https://arquivos.arcoconsultoria.com/arquivos/siga/BVIX/2025-00001/"
             "bd98c5b6-b183-496c-bd3a-134aba1e25cf-TERMO_assinado.pdf';\n$mainform().hideWait();")
    m = re.search(r"_ruleReturn\s*=\s*'(https?://[^']+)'", corpo)
    assert m.group(1).endswith("-TERMO_assinado.pdf")
