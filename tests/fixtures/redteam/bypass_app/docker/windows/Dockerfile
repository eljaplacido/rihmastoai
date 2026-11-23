# escape=`
# The backtick continues the RUN line, so the USER line below is part of it: the image runs as its admin.
# seeded below: RT-DOCKER-ROOT
FROM mcr.microsoft.com/windows/servercore:ltsc2022
RUN echo building `
USER ContainerUser
CMD ["cmd"]
