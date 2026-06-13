╭─[jonat@DESKTOP-C6GV5KV]─[~\..\..\SE4-AI-Agent]                                            ()─[10,21:28]
╰─[ main ● ?1 ~2]- & c:\Users\jonat\Documents\GitHub\SE4-AI-Agent\.venv\Scripts\python.exe c:/Users/jonat/Documents/GitHub/SE4-AI-Agent/testScript/j3.test.py^C
╭─[jonat@DESKTOP-C6GV5KV]─[~\..\..\SE4-AI-Agent]                                            ()─[10,21:28]
╰─[ main ● ?1 ~2]- (Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned) ; (& c:\Users\jonat\Documents\GitHub\SE4-AI-Agent\.venv\Scripts\Activate.ps1)
╭─[jonat@DESKTOP-C6GV5KV]─[~\..\..\SE4-AI-Agent]                      (SE4-AI-Agent 3.12.10)()─[10,21:28]
╰─[ main ● ?1 ~2]- & c:\Users\jonat\Documents\GitHub\SE4-AI-Agent\.venv\Scripts\python.exe c:/Users/jonat/Documents/GitHub/SE4-AI-Agent/testScript/j3.test.py
=== Supermarkt Vergelijker (Echte API Editie) ===
Typ 'stop' om af te sluiten.

Jij: ik wil graag 2 citroenen, redbull en chocomelk in Den Haag Hollands Spoor
[Agent]: Boodschappenlijst en locatie extraheren...
[Agent]: Live prijzen ophalen via SupermarktConnector...
  [Debug] Start AH zoekopdracht voor: 'citroen'...
  [Debug] AH succesvol voor: 'citroen'
  [Debug] Start Jumbo zoekopdracht voor: 'citroen'...
  [Waarschuwing] Jumbo API faalde voor 'citroen': 403 Client Error: Forbidden for url: https://mobileapi.jumbo.com/v17/search?offset=0&limit=1&q=citroen
Traceback (most recent call last):
  File "c:\Users\jonat\Documents\GitHub\SE4-AI-Agent\testScript\j3.test.py", line 213, in <module>
    result = app.invoke({"user_input": user_input}, config)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\jonat\Documents\GitHub\SE4-AI-Agent\.venv\Lib\site-packages\langgraph\pregel\main.py", line 3884, in invoke
    for chunk in self.stream(
                 ^^^^^^^^^^^^
  File "C:\Users\jonat\Documents\GitHub\SE4-AI-Agent\.venv\Lib\site-packages\langgraph\pregel\main.py", line 2938, in stream
    for _ in runner.tick(
             ^^^^^^^^^^^^
  File "C:\Users\jonat\Documents\GitHub\SE4-AI-Agent\.venv\Lib\site-packages\langgraph\pregel\_runner.py", line 207, in tick
    run_with_retry(
  File "C:\Users\jonat\Documents\GitHub\SE4-AI-Agent\.venv\Lib\site-packages\langgraph\pregel\_retry.py", line 617, in run_with_retry
    return task.proc.invoke(task.input, config)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\jonat\Documents\GitHub\SE4-AI-Agent\.venv\Lib\site-packages\langgraph\_internal\_runnable.py", line 684, in invoke
    input = context.run(step.invoke, input, config, **kwargs)
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\jonat\Documents\GitHub\SE4-AI-Agent\.venv\Lib\site-packages\langgraph\_internal\_runnable.py", line 426, in invoke
    ret = self.func(*args, **kwargs)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "c:\Users\jonat\Documents\GitHub\SE4-AI-Agent\testScript\j3.test.py", line 119, in node_vergelijk_prijzen
    ah_totaal += ah_prijs
TypeError: unsupported operand type(s) for +=: 'float' and 'NoneType'
During task with name 'vergelijk_prijzen' and id '7f6d6e71-2742-616e-c156-3fc0efcab826'